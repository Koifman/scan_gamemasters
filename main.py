# This Python file uses the following encoding: utf-8
import json
import os
import random
import time
import sys
import logging

import requests
import click
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Character, Realm

SLEEP_INTERVAL = 0.3

basedir = os.path.abspath(os.path.dirname(__file__))
DB_PATH = 'sqlite:///' + os.path.join(basedir, 'db.db')

guilds_scanned = {}
realm_cache = {}


# initialize database

engine = create_engine(DB_PATH)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

CHAR_API_URL = "http://{region}.battle.net/api/wow/character/{realm}/{character}?fields=pets,{guild}"
GUILD_API_URL = "http://{region}.battle.net/api/wow/guild/{realm}/{guild_name}?fields=members"
AUCTION_API_URL = "http://{region}.battle.net/api/wow/auction/data/{realm_slug}"
CHARACTER_ARMORY_URL = "http://{region}.battle.net/wow/en/character/{realm_slug}/{char_name}/simple"


class Statistics(object):
    def __init__(self):
        self.realm = None
        self.start_time = time.time()
        self.chars_scanned = 0
        self.gms_found = 0
        self.in_queue = 0

    def get_rate(self):
        """
        Compute scanning rate, measured in characters per second
        """
        now = time.time()
        elapsed = now - self.start_time
        char_per_sec = self.chars_scanned / elapsed
        return char_per_sec

    def print_stats(self):
        # clear terminal
        clear_screen()
        print("Scanning %s" % self.realm.name)
        print("Characters scanned (total): %s" % self.chars_scanned)
        print("Possible gamemasters found: %s" % self.gms_found)
        print("Characters in queue: %s" % self.in_queue)
        print("Scan rate: %.2f characters per second" % self.get_rate())


def clear_screen():
    if sys.platform.startswith("win"):
        os.system("cls")
    else:
        os.system("clear")


def load_json_from_url(url):
    # sometimes blizzard api does not return data, try until it does
    while True:
        r = requests.get(url)
        if "Refresh" not in r.headers:
            break
        time.sleep(1)
    data = json.loads(r.text)
    return data


def load_auction_data(realm):
    url = AUCTION_API_URL.format(region=realm.region, realm_slug=realm.slug)
    data = load_json_from_url(url)
    try:
        auction_dump_url = data["files"][0]["url"]
    except KeyError:
        logging.exception("Can't get auction dump url. Response from api: %s" % str(data))
        raise
    data = load_json_from_url(auction_dump_url)
    return data


def get_realm(region, realm_name):
    """
    Get Realm object from database
    """
    key = "".join([region, realm_name])
    if key in realm_cache:
        return realm_cache[key]
    realm = session.query(Realm).filter(Realm.region == region,
                                        (Realm.name_localised == realm_name) | (Realm.name == realm_name)).first()
    realm_cache[key] = realm
    return realm


def insert_chars_from_auc(realm):
    """
    Insert all player characters represented in auction house into database
    note: realm names in auction house dump are always localised, with spaces removed
    """
    auc_data = load_auction_data(realm)
    region = realm.region
    unique_auc_chars = set((lot["owner"], lot["ownerRealm"]) for lot in auc_data["auctions"]["auctions"])
    print("Unique chars currently on %s auction house: %d" % (realm.name, len(unique_auc_chars)))
    for name, realm_name_localised in unique_auc_chars:
        realm = get_realm(region, realm_name_localised)
        char = Character()
        char.name = name
        char.realm = realm
        char.retrieve_guild = True
        if not session.query(Character).filter(Character.name == char.name,
                                               Character.realm == char.realm).first():
            session.add(char)
    session.commit()


def is_gm(text):
    """
    Search for "Panda Cub" pet, which most gamemasters apparently possess
    """
    return "Panda Cub" in text



def save_gm_to_file(name, realm, armory_url):
    with open("gms.txt", "a") as f:
        f.write("%s (%s) %s" % (name, realm, armory_url))
        f.write("\n")


def submit_gm(char):
    """
    Submit character name and realm to http://wow-gm-track.website/
    All submission are aggregated to the main database, allowing one to view
    additional data about the character, such as twinks, info about collector's editions
    acquired by character, and more
    Recent submissions can be viewed at http://wow-gm-track.website/submissions
    """
    data = {
        "realm_slug": char.realm.slug,
        "char_name": char.name,
        "region": char.realm.region
    }
    try:
        requests.post("http://wow-gm-track.website/api/add_char", data=data)
    except Exception:
        print("Could not submit character data to http://wow-gm-track.website/api/add_char")


def scan_character(char, chars_to_scan):
    time.sleep(SLEEP_INTERVAL)
    url = CHAR_API_URL.format(region=char.realm.region, character=char.name, realm=char.realm.slug,
                              guild="guild" if char.retrieve_guild is True else "")
    r = requests.get(url)
    if r.status_code != 200:
        char.is_scanned = True
        return char
    if is_gm(r.text):
        armory_url = CHARACTER_ARMORY_URL.format(region=char.realm.region, realm_slug=char.realm.slug,
                                                 char_name=char.name)

        char.is_gm = True
        save_gm_to_file(char.name, char.realm.name, armory_url)
        submit_gm(char)
    char.is_scanned = True
    if not char.retrieve_guild:
        return char

    # now add all members of the guild to database
    data = json.loads(r.text)
    if "guild" in data:
        guild_name = data["guild"]["name"]
        if guild_name not in guilds_scanned:
            insert_chars_from_guild(char.realm, guild_name, chars_to_scan)
            guilds_scanned[guild_name] = True
    return char


def insert_chars_from_guild(realm, guild_name, chars_to_scan):
    data = load_json_from_url(GUILD_API_URL.format(region=realm.region, realm=realm.name, guild_name=guild_name))

    # sometimes api returns error for a valid guild name
    try:
        members = data["members"]
    except KeyError:
        logging.exception("No data return for guild name: %s, realm: %s" % (guild_name, realm.name))
        return

    for member in members:
        name = member["character"]["name"]

        # sometimes there is a character without realm. Possibly because it was deleted/transferred/renamed recently
        realm_name = member["character"].get("realm")
        if realm_name is None:
            continue

        realm = get_realm(realm.region, realm.name)
        char = Character()
        char.name = name
        char.realm = realm
        char.retrieve_guild = False
        if not session.query(Character).filter(Character.name == char.name,
                                               Character.realm == char.realm).first() and char not in session:
            session.add(char)
            chars_to_scan.append(char)
    session.commit()


def main(realms_to_scan, randomize_order):
    if randomize_order:
        random.shuffle(realms_to_scan)
    stats = Statistics()
    while True:
        for realm in realms_to_scan:
            # print_mem_usage()
            stats.realm = realm
            insert_chars_from_auc(realm)
            chars_to_scan = session.query(Character).filter(Character.realm == realm,
                                                            Character.is_scanned == False).all()
            random.shuffle(chars_to_scan)
            print(len(chars_to_scan))
            while chars_to_scan:
                char = chars_to_scan.pop()
                char = scan_character(char, chars_to_scan)
                session.add(char)
                session.commit()

                # update statistics
                stats.chars_scanned += 1
                stats.in_queue = len(chars_to_scan)
                if char.is_gm:
                    stats.gms_found += 1
                stats.print_stats()
        # wait 30 minutes and scan again
        print("Finished scanning, waiting 30 minutes until next round.")
        time.sleep(30 * 60)


def is_empty_db():
    realm = session.query(Realm).first()
    return realm is None


def populate_realms_db():
    """
    If user executes script for the first time, populate db with realm names
    """
    print("Populating database with realm names, might take a few minutes")
    url = "http://{region}.battle.net/api/wow/realm/status?locale={locale}"
    regions = {
        "eu": ['de_DE', 'en_GB', 'pt_BR', 'fr_FR', 'ru_RU', 'es_ES', 'it_IT'],
        "us": ["en_US", "es_MX", "pt_BR"],
        "kr": ["ko_KR"],
        "tw": ["zh_TW"],
    }
    for region in regions:
        locales = regions[region]
        for locale in locales:
            r = requests.get(url.format(region=region, locale=locale))
            data = json.loads(r.text)
            for realm in data["realms"]:
                if realm["locale"] == locale:
                    english_name = get_eng_rlm_name(realm["slug"], region)
                    # print(region, locale, realm["name"], english_name, realm["slug"])
                    rlm = Realm()
                    rlm.name = english_name
                    # Localised names in AH dump are without spaces
                    rlm.name_localised = realm["name"].replace(" ", "")
                    rlm.slug = realm["slug"]
                    rlm.region = region
                    rlm.locale = locale
                    session.add(rlm)
    session.commit()


def get_eng_rlm_name(name, region):
    """
    Convert localised realm name to english one
    """
    url = "http://%s.battle.net/api/wow/realm/status?realms=%s" % (region, name)
    r = requests.get(url)
    data = json.loads(r.text)
    return data["realms"][0]["name"]


@click.command()
@click.option("--region", help="Region in which to perform scan. Available regions: us, eu, kr, tw.")
@click.option("--realm", help="Scan specific realm. "
                              "For example: --realm Outland")
@click.option("--locale", help="Scan realms with specific locale. "
                               "Available locales: "
                               "de_DE en_GB en_US es_ES es_MX fr_FR it_IT pt_BR ru_RU")
@click.option('--randomize', is_flag=True, help="Randomize the order in which realms are scanned.")
def start(region, realm, locale, randomize):
    """
    Find probable Blizzard employee's characters in World of Warcraft using battle.net API.
    """
    if is_empty_db():
        populate_realms_db()
    realms_to_scan = []
    if region and realm:
        realms_to_scan = session.query(Realm).filter(Realm.region == region,
                                                     (Realm.name_localised == realm.replace(" ",
                                                                                            "")) | (
                                                         Realm.name == realm)).all()
    elif region and locale:
        realms_to_scan = session.query(Realm).filter(Realm.region == region,
                                                     Realm.locale == locale).all()
    elif realm:
        realms_to_scan = session.query(Realm).filter(
            (Realm.name == realm.replace(" ", "")) | (Realm.name_localised == realm)).all()
    elif locale:
        realms_to_scan = session.query(Realm).filter(
            (Realm.name == realm.replace(" ", "")) | (Realm.name_localised == realm)).all()
    elif region:
        realms_to_scan = session.query(Realm).filter(Realm.region == region).all()
    else:
        # if no parameters are specified, select random realm for scan
        ids = session.query(Realm.id).filter(Realm.region == "eu").all()
        realms_to_scan.append(session.query(Realm).get(random.choice(ids)))

    if not realms_to_scan:
        click.echo("Could not find any realms with parameters you specified.")
        sys.exit()
    main(realms_to_scan, randomize_order=randomize)


if __name__ == "__main__":
    start()
