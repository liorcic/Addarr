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
logger = logger.getLogger("addarr.radarr", logLevel, config.get("logToConsole", False))

config = config["radarr"]

addMovieNeededFields = ["tmdbId", "year", "title", "titleSlug", "images"]


def search(title):
    parameters = {"term": title}
    req = requests.get(commons.generateApiQuery("radarr", "movie/lookup", parameters))
    parsed_json = json.loads(req.text)

    if req.status_code == 200 and parsed_json:
        return parsed_json
    else:
        return False


def giveTitles(parsed_json):
    data = []
    for movie in parsed_json:
        if all(
            x in movie for x in ["title", "overview", "remotePoster", "year", "tmdbId"]
        ):
            data.append(
                {
                    "title": movie["title"],
                    "overview": movie["overview"],
                    "poster": movie["remotePoster"],
                    "year": movie["year"],
                    "id": movie["tmdbId"],
                }
            )
    return data


def inLibrary(tmdbId):
    parameters = {}
    req = requests.get(commons.generateApiQuery("radarr", "movie", parameters))
    parsed_json = json.loads(req.text)
    return next((True for movie in parsed_json if movie["tmdbId"] == tmdbId), False)


def addToLibrary(tmdbId, path, profile):
    parameters = {"tmdbId": str(tmdbId)}
    req = requests.get(
        commons.generateApiQuery("radarr", "movie/lookup/tmdb", parameters)
    )
    parsed_json = json.loads(req.text)
    data = json.dumps(buildData(parsed_json, path, profile))
    add = requests.post(commons.generateApiQuery("radarr", "movie"), data=data)
    if add.status_code == 201:
        return True
    else:
        return False


def buildData(json, path, profile):
    built_data = {
        "qualityProfileId": profile,
        "rootFolderPath": path,  # config["rootFolder"],
        "addOptions": {"searchForMovie": config["search"]},
    }

    for key in addMovieNeededFields:
        built_data[key] = json[key]
    return built_data


def getRootFolders():
    req = requests.get(commons.generateApiQuery("radarr", "Rootfolder"))
    parsed_json = json.loads(req.text)
    logger.debug(f"Found Radarr paths: {parsed_json}")
    return parsed_json


def getProfiles():
    req = requests.get(commons.generateApiQuery("radarr", "qualityProfile"))
    parsed_json = json.loads(req.text)
    logger.debug(f"Found Radarr Profiles: {parsed_json}")
    return parsed_json


def get_queue_pourcentage():
    req = requests.get(commons.generateApiQuery("radarr", "queue"))
    parsed_json = json.loads(req.text)
    logger.debug(f"Found Radarr Queue")

    movies_in_queue = {}
    for item in parsed_json["records"]:
        movie_title = item["title"]
        movie_status = item["status"]
        movie_pourcentage = ((item["size"] - item["sizeleft"]) / item["size"]) * 100
        movie_pourcentage = round(movie_pourcentage, 2)
        if movie_status == "downloading":
            movies_in_queue[movie_title] = movie_pourcentage
    return movies_in_queue
