from typing import List

class Attribute():
  key: str | None
  value: str | None

class SearchObject():
    def __init__(self, id: str, name: str, attributes: List[Attribute]):
        self.id = id
        self.name = name
        self.attributes = attributes

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "attributes": self.attributes
        }
