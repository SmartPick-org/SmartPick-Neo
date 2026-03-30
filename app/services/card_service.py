
class CardService: # Dependency Injection
    def __init__(self, card_repo: CardRepository):
        self.card_repo = card_repo

    def _calculation(self, card: Card) -> Card:
        pass