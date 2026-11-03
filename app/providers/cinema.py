"""CinemaPlus public-page provider export and separately labeled TMDB metadata."""

import re

from app.providers.http import ProviderFailure
from app.providers.models import MovieMetadata, Provenance, ProviderResult, unavailable
from app.providers.cinemaplus import CinemaPlusPublicProvider as CinemaPlusProvider

OFFICIAL = "https://cinemastercard.az/"
TMDB = "https://api.themoviedb.org/3"
NOTICE = ("TMDB movie metadata only. These are not confirmed CinemaPlus screenings. "
          "Official CinemaPlus public listings are a separate source. This metadata result does not "
          "verify showtimes, ticket prices or seat availability. Check cinemastercard.az for tickets.")


class TMDBProvider:
    name = "TMDB"

    def __init__(self, http, token=None):
        self.http, self.token = http, token

    async def search(self, p):
        if not self.token:
            return unavailable(self.name, "https://www.themoviedb.org/", "Set TMDB_READ_ACCESS_TOKEN to enable movie metadata. " + NOTICE, "missing_credentials")
        try:
            params = {"language": "en-US", "include_adult": "false", "page": 1}
            if p.movie_title:
                params["query"] = p.movie_title
                path = "/search/movie"
            else:
                path = "/discover/movie"
            doc = await self.http.get(TMDB + path, params=params, headers={"Authorization": "Bearer " + self.token})
            if not isinstance(doc.data, dict) or not isinstance(doc.data.get("results"), list):
                raise ProviderFailure("invalid_response")
            genres = {}
            if p.genre:
                genre_doc = await self.http.get(TMDB + "/genre/movie/list", params={"language": "en-US"},
                    headers={"Authorization": "Bearer " + self.token}, ttl=86400)
                if not isinstance(genre_doc.data, dict) or not isinstance(genre_doc.data.get("genres"), list):
                    raise ProviderFailure("invalid_response")
                genres = {g["id"]: g["name"] for g in genre_doc.data["genres"]}
            rows = []
            for raw in doc.data["results"]:
                movie = self.normalize(raw)
                if p.min_rating is not None and (movie.rating is None or movie.rating < p.min_rating):
                    continue
                if p.language and p.language.casefold() != (movie.language or "").casefold():
                    continue
                if p.genre:
                    movie.genre = [genres[g] for g in raw.get("genre_ids", []) if g in genres]
                    requested = "science fiction" if p.genre.casefold() == "sci-fi" else p.genre.casefold()
                    if requested not in {g.casefold() for g in movie.genre}:
                        continue
                rows.append(movie)
            if p.sort_by:
                if p.sort_by not in {"rating_desc", "rating_asc", "title_asc", "title_desc"}:
                    raise ProviderFailure("invalid_sort")
                field, order = p.sort_by.split("_")
                rows.sort(key=lambda r: (r.rating or 0) if field == "rating" else r.title.casefold(), reverse=order == "desc")
            return self.result(doc, rows, partial=True)
        except ProviderFailure as exc:
            if exc.code == "invalid_response":
                self.http.discard()
            return unavailable(self.name, "https://www.themoviedb.org/", NOTICE + " Metadata unavailable: " + exc.code.replace("_", " "), exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError):
            self.http.discard()
            return unavailable(self.name, "https://www.themoviedb.org/", "TMDB returned invalid data. " + NOTICE, "invalid_response")

    async def details(self, movie_id):
        if not re.fullmatch(r"TMDB-[0-9]+", movie_id):
            return unavailable(self.name, "https://www.themoviedb.org/", "Choose a TMDB movie ID.", "unknown_id")
        if not self.token:
            return unavailable(self.name, "https://www.themoviedb.org/", "TMDB credentials are missing. " + NOTICE, "missing_credentials")
        try:
            doc = await self.http.get(TMDB + "/movie/" + movie_id[5:], params={"language": "en-US"},
                                      headers={"Authorization": "Bearer " + self.token})
            return self.result(doc, [self.normalize(doc.data)])
        except ProviderFailure as exc:
            return unavailable(self.name, "https://www.themoviedb.org/", "TMDB metadata unavailable. " + NOTICE, exc.code, exc.retry_after)
        except (KeyError, ValueError, TypeError):
            self.http.discard()
            return unavailable(self.name, "https://www.themoviedb.org/", "TMDB returned invalid data. " + NOTICE, "invalid_response")

    @staticmethod
    def normalize(raw):
        identifier = int(raw["id"])
        if identifier <= 0 or not raw["title"]:
            raise ValueError("Invalid movie")
        poster = raw.get("poster_path")
        return MovieMetadata(id=f"TMDB-{identifier}", title=raw["title"], synopsis=raw.get("overview") or "",
            genre=[g["name"] for g in raw.get("genres", [])], rating=raw.get("vote_average"),
            language=raw.get("original_language"), duration_min=raw.get("runtime"), release_date=raw.get("release_date"),
            poster_url="https://image.tmdb.org/t/p/w500" + poster if isinstance(poster, str) and re.fullmatch(r"/[\w.-]+", poster) else None,
            metadata_url=f"https://www.themoviedb.org/movie/{identifier}")

    def result(self, doc, rows, partial=False):
        return ProviderResult(source=Provenance(provider=self.name, status="cached" if doc.cached else "live",
            fetched_at=doc.fetched_at, local_cache_hit=doc.cached, source_url="https://www.themoviedb.org/", notice=NOTICE), items=rows, partial=partial)
