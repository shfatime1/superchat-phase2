"""Birmarket authorization boundary: merchant access is not public catalog access."""

from app.providers.models import unavailable


class BirmarketProvider:
    name = "Birmarket"
    website = "https://birmarket.az/"
    capabilities = {feature: False for feature in
        ("search", "categories", "details", "prices", "images", "stock")}

    def authorization_required(self):
        return unavailable(self.name, self.website,
            "Birmarket catalog access requires authorization and official integration documentation. "
            "Seller APIs concern the merchant account; public catalog search, categories, product details, "
            "prices, images and stock access have not been verified. Browse birmarket.az directly.")

    async def search(self, parameters):
        return self.authorization_required()

    async def categories(self):
        return self.authorization_required()

    async def details(self, product_id):
        return self.authorization_required()
