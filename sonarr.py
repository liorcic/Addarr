#!/usr/bin/env python3

import commons as commons
import json
import logging
import requests
import yaml

import logger
from definitions import CONFIG_PATH

config = yaml.safe_load(open(CONFIG_PATH, encoding="utf8"))

# Set up logging
logLevel = logging.DEBUG if config.get("debugLogging", False) else logging.INFO
logger = logger.getLogger("addarr.sonarr", logLevel, config.get("logToConsole", False))

config = config["sonarr"]

addSerieNeededFields = ["tvdbId", "tvRageId", "title", "titleSlug", "images", "seasons"]


def search(title):
    parameters = {"term": title}
    req = requests.get(commons.generateApiQuery("sonarr", "series/lookup", parameters))
    parsed_json = json.loads(req.text)

    if req.status_code == 200 and parsed_json:
        return parsed_json
    else:
        return False


def giveTitles(parsed_json):
    data = []
    for show in parsed_json:
        if all(
            x in show
            for x in ["title", "seasonCount", "remotePoster", "year", "tvdbId"]
        ):
            data.append(
                {
                    "title": show["title"],
                    "seasonCount": show["seasonCount"],
                    "poster": show["remotePoster"],
                    "year": show["year"],
                    "id": show["tvdbId"],
                    "monitored": show["monitored"],
                    "status": show["status"],
                }
            )
    return data

def inLibrary(tvdbId):
    parameters = {}
    req = requests.get(commons.generateApiQuery("sonarr", "series", parameters))
    parsed_json = json.loads(req.text)
    return next((True for show in parsed_json if show["tvdbId"] == tvdbId), False)


def addToLibrary(tvdbId, path, profile):
    parameters = {"term": "tvdb:" + str(tvdbId)}
    req = requests.get(commons.generateApiQuery("sonarr", "series/lookup", parameters))
    parsed_json = json.loads(req.text)
    data = json.dumps(buildData(parsed_json, path, profile))
    add = requests.post(commons.generateApiQuery("sonarr", "series"), data=data)
    if add.status_code == 201:
        return True
    else:
        return False


def buildData(json, path, profile):
    built_data = {
        "qualityProfileId": profile,
        "addOptions": {
            "ignoreEpisodesWithFiles": "true",
            "ignoreEpisodesWithoutFiles": "false",
            "searchForMissingEpisodes": config["search"],
        },
        "rootFolderPath": path,  # config["rootFolder"],
        "seasonFolder": config["seasonFolder"],
    }

    for show in json:
        for key, value in show.items():
            if key in addSerieNeededFields:
                built_data[key] = value
    return built_data


def getRootFolders():
    parameters = {}
    req = requests.get(commons.generateApiQuery("sonarr", "Rootfolder", parameters))
    parsed_json = json.loads(req.text)
    # Remove unmappedFolders from rootFolder data--we don't need that
    for item in [
        item for item in parsed_json if item.get("unmappedFolders") is not None
    ]:
        item.pop("unmappedFolders")
    logger.debug(f"Found sonarr paths: {parsed_json}")
    return parsed_json

def getProfiles():
    req = requests.get(commons.generateApiQuery("sonarr", "profile"))
    parsed_json = json.loads(req.text)
    return parsed_json

def allSeries():
    parameters = {}
    req = requests.get(commons.generateApiQuery("sonarr", "series", parameters))
    parsed_json = json.loads(req.text)

    if req.status_code == 200:
        data = []
        for show in parsed_json:
            if all(
                x in show
                for x in ["title", "year", "monitored", "status", "id", "seasonCount"]
            ):
                data.append(
                    {
                        "title": show["title"],
                        "year": show["year"],
                        "monitored": show["monitored"],
                        "status": show["status"],
                        "id": show["id"],
                        "seasonCount": show["seasonCount"]
                    }
                )
        return data
    else:
        return False


def searchSeason(seriesId, seasonNumber):
    data = {"name": "SeasonSearch", "seriesId": seriesId, "seasonNumber": seasonNumber}
    req = requests.post(commons.generateApiQuery("sonarr", "command"), json=data)
    return req.status_code == 201


def get_queue_pourcentage():
    req = requests.get(commons.generateApiQuery("sonarr", "queue"))
    parsed_json = json.loads(req.text)
    logger.debug(f"Found sonarr Queue")

    series_in_queue = {}
    for item in parsed_json:
        movie_title = item["title"]
        movie_status = item["status"]
        movie_pourcentage = ((item["size"] - item["sizeleft"]) / item["size"]) * 100
        movie_pourcentage = round(movie_pourcentage, 2)
        if movie_status == "Downloading":
            series_in_queue[movie_title] = movie_pourcentage
    return series_in_queue
