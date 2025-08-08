from typing import List
from pydantic import BaseModel, computed_field

class SearchAttribute(BaseModel):
  key: str | None
  value: str | None

class SearchObject(BaseModel):
    id: str
    name: str
    attributes: List[SearchAttribute] | None = None

    @computed_field
    def display_name(self) -> str:
        return f"{self.id}: {self.name}"

class SearchPublic(BaseModel):
    items: List[SearchObject] | None = None
    total: int
    page: int
    per_page: int
