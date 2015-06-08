# This Python file uses the following encoding: utf-8
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship

Base = declarative_base()


class Character(Base):
    __tablename__ = "character"
    __table_args__ = (UniqueConstraint("name", "realm_id", name='uix_1'),)

    id = Column(Integer, primary_key=True)
    name = Column(String)
    realm_id = Column(Integer, ForeignKey("realm.id"))
    realm = relationship("Realm")
    is_gm = Column(Boolean, default=False)
    is_scanned = Column(Boolean, default=False)
    retrieve_guild = Column(Boolean, default=False)

    def __repr__(self):
        return "<Character(name=%s, realm=%s)>" % (self.name, self.realm.name)


class Realm(Base):
    __tablename__ = "realm"

    id = Column(Integer, primary_key=True)
    region = Column(String)
    name = Column(String)
    name_localised = Column(String)
    slug = Column(String)
    locale = Column(String)
