#!/usr/bin/env python3
from flask import Flask, request
import threading
import logging
import re
import os
import math

import json
import yaml
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Updater,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)

from definitions import CONFIG_PATH, LANG_PATH, CHATID_PATH, ADMIN_PATH, REQUESTS_PATH
import radarr as radarr
import sonarr as sonarr
import logger
import requests

__version__ = "0.3"

config = yaml.safe_load(open(CONFIG_PATH, encoding="utf8"))

# Set up logging
logLevel = logging.DEBUG if config.get("debugLogging", False) else logging.INFO
logger = logger.getLogger("addarr", logLevel, config.get("logToConsole", False))
logger.debug(f"Addarr v{__version__} starting up...")

SERIE_MOVIE_AUTHENTICATED, READ_CHOICE, GIVE_OPTION, GIVE_PATHS, GIVE_PROFILES, TSL_NORMAL, CHOOSE_SERIE, CHOOSE_SEASON = range(8)

updater = Updater(config["telegram"]["token"], use_context=True)
dispatcher = updater.dispatcher
lang = config["language"]

transcript = yaml.safe_load(open(LANG_PATH, encoding="utf8"))
transcript = transcript[lang]


def main():
    auth_handler_command = CommandHandler(config["entrypointAuth"], authentication)
    auth_handler_text = MessageHandler(
                            Filters.regex(
                                re.compile(r"" + config["entrypointAuth"] + "", re.IGNORECASE)
                            ),
                            authentication,
                        )
    allSeries_handler_command = CommandHandler(config["entrypointAllSeries"], allSeries)
    allSeries_handler_text = MessageHandler(
                            Filters.regex(
                                re.compile(r"" + config["entrypointAllSeries"] + "", re.IGNORECASE)
                            ),
                            allSeries,
                        )
    addMovieserie_handler = ConversationHandler(
        entry_points=[
            CommandHandler(config["entrypointAdd"], startSerieMovie),
            CommandHandler(transcript["Movie"], startSerieMovie),
            CommandHandler(transcript["Serie"], startSerieMovie),
            MessageHandler(
                Filters.regex(
                    re.compile(r"" + config["entrypointAdd"] + "", re.IGNORECASE)
                ),
                startSerieMovie,
            ),
        ],
        states={
            SERIE_MOVIE_AUTHENTICATED: [MessageHandler(Filters.text, choiceSerieMovie)],
            READ_CHOICE: [
                MessageHandler(
                    Filters.regex(f'^({transcript["Movie"]}|{transcript["Serie"]})$'),
                    searchSerieMovie,
                )
            ],
            GIVE_OPTION: [
                MessageHandler(Filters.regex(f'({transcript["Add"]})'), pathSerieMovie),
                MessageHandler(
                    Filters.regex(f'({transcript["Next result"]})'), nextOption
                ),
                MessageHandler(
                    Filters.regex(f'({transcript["New"]})'), startSerieMovie
                ),
            ],
            GIVE_PATHS: [
                MessageHandler(
                    Filters.regex(re.compile(r"^(Path: )(.*)$", re.IGNORECASE)),
                    languageSerieMovie,
                ),
            ],
            GIVE_PROFILES: [
                MessageHandler(
                    Filters.regex(re.compile(r"^(.*)$", re.IGNORECASE)),
                    addSerieMovie,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("stop", stop),
            MessageHandler(Filters.regex("^(Stop|stop)$"), stop),
        ],
    )

    download_season_handler = ConversationHandler(
        entry_points=[
            CommandHandler(config["season"], chooseSerie)
        ],
        states={
            CHOOSE_SERIE: [MessageHandler(Filters.text, chooseSeason)],
            CHOOSE_SEASON: [MessageHandler(Filters.text, searchSeason)],
        },
        fallbacks=[
            CommandHandler("stop", stop),
            MessageHandler(Filters.regex("^(Stop|stop)$"), stop),
        ],
    )

    changeTransmissionSpeed_handler = ConversationHandler(
        entry_points=[
            CommandHandler(config["entrypointTransmission"], transmission),
            MessageHandler(
                Filters.regex(
                    re.compile(
                        r"" + config["entrypointTransmission"] + "", re.IGNORECASE
                    )
                ),
                transmission,
            ),
        ],
        states={TSL_NORMAL: [MessageHandler(Filters.text, changeSpeedTransmission)]},
        fallbacks=[
            CommandHandler("stop", stop),
            MessageHandler(Filters.regex("^(Stop|stop)$"), stop),
        ],
    )
    pourcentage_handler_command = CommandHandler(config["entrypointPourcentage"], pourcentage)

    dispatcher.add_handler(auth_handler_command)
    dispatcher.add_handler(auth_handler_text)
    dispatcher.add_handler(allSeries_handler_command)
    dispatcher.add_handler(allSeries_handler_text)
    dispatcher.add_handler(addMovieserie_handler)
    dispatcher.add_handler(changeTransmissionSpeed_handler)
    dispatcher.add_handler(pourcentage_handler_command)
    dispatcher.add_handler(download_season_handler)

    logger.info(transcript["Start chatting"])
    updater.start_polling()
    updater.idle()


# Check if Id is authenticated
def checkId(update):
    authorize = False
    with open(CHATID_PATH, "r") as file:
        firstChar = file.read(1)
        if not firstChar:
            return False
        file.close()
    with open(CHATID_PATH, "r") as file:
        for line in file:
            if line.strip("\n") == str(update.effective_message.chat_id):
                authorize = True
        file.close()
        if authorize:
            return True
        else:
            return False


# Check if user is an admin
def checkAdmin(update):
    admin = False
    user = update.message.from_user
    with open(ADMIN_PATH, "r") as file:
        for line in file:
            if line.strip("\n") == str(user["username"]) or line.strip("\n") == str(
                user["id"]
            ):
                admin = True
        file.close()
        if admin:
            return True
        else:
            return False


def transmission(
    update, context,
):
    if config["transmission"]["enable"]:
        if checkId(update):
            if checkAdmin(update):
                reply_keyboard = [
                    [
                        transcript["Transmission"]["TSL"],
                        transcript["Transmission"]["Normal"],
                    ]
                ]
                markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
                update.message.reply_text(
                    transcript["Transmission"]["Speed"], reply_markup=markup
                )
                return TSL_NORMAL
            else:
                context.bot.send_message(
                    chat_id=update.effective_message.chat_id,
                    text=transcript["NotAdmin"],
                )
                return TSL_NORMAL
        else:
            context.bot.send_message(
                chat_id=update.effective_message.chat_id, text=transcript["Authorize"]
            )
            return TSL_NORMAL
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript["Transmission"]["NotEnabled"],
        )
        return ConversationHandler.END


def changeSpeedTransmission(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    else:
        choice = update.message.text
        if choice == transcript["Transmission"]["TSL"]:
            if config["transmission"]["authentication"]:
                auth = (
                    " --auth "
                    + config["transmission"]["username"]
                    + ":"
                    + config["transmission"]["password"]
                )
            os.system(
                "transmission-remote "
                + config["transmission"]["host"]
                + auth
                + " --alt-speed"
            )
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript["Transmission"]["ChangedToTSL"],
            )
            return ConversationHandler.END

        elif choice == transcript["Transmission"]["Normal"]:
            if config["transmission"]["authentication"]:
                auth = (
                    " --auth "
                    + config["transmission"]["username"]
                    + ":"
                    + config["transmission"]["password"]
                )
            os.system(
                "transmission-remote "
                + config["transmission"]["host"]
                + auth
                + " --no-alt-speed"
            )
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript["Transmission"]["ChangedToNormal"],
            )
            return ConversationHandler.END


def authentication(update, context):
    chatid = update.effective_message.chat_id
    with open(CHATID_PATH, "r") as file:
        if(str(chatid) in file.read()):
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript["Chatid already allowed"],
            )                
            file.close()
        else:
            file.close()
            password = update.message.text
            if("/auth" in password):
                password = password.replace("/auth ", "")
            if password == config["telegram"]["password"]:
                with open(CHATID_PATH, "a") as file:
                    file.write(str(chatid) + "\n")
                    context.bot.send_message(
                        chat_id=update.effective_message.chat_id,
                        text=transcript["Chatid added"],
                    )
                    file.close()
                    return "added"
            else:
                logger.warning(
                    f"Failed authentication attempt by [{update.message.from_user.username}]. Password entered: [{password}]"
                )
                context.bot.send_message(
                    chat_id=update.effective_message.chat_id, text=transcript["Wrong password"]
                )
                return ConversationHandler.END # This only stops the auth conv, so it goes back to choosing screen
            


def stop(update, context):
    clearUserData(context)
    context.bot.send_message(
        chat_id=update.effective_message.chat_id, text=transcript["End"],
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def startSerieMovie(update, context):
    if checkId(update):
        if update.message.text[1:].lower() in [
            transcript["Serie"].lower(),
            transcript["Movie"].lower(),
        ]:
            logger.debug(
                f"User issued {update.message.text} command, so setting user_data[choice] accordingly"
            )
            context.user_data.update(
                {
                    "choice": transcript["Serie"]
                    if update.message.text[1:].lower() == transcript["Serie"].lower()
                    else transcript["Movie"]
                }
            )
        elif update.message.text.lower() == transcript["New"].lower():
            logger.debug("User issued New command, so clearing user_data")
            clearUserData(context)
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=transcript["Title"]
        )
        return SERIE_MOVIE_AUTHENTICATED
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=transcript["Authorize"]
        )
        return SERIE_MOVIE_AUTHENTICATED


def choiceSerieMovie(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    else:
        text = update.message.text
        if text[1:].lower() not in [
            transcript["Serie"].lower(),
            transcript["Movie"].lower(),
        ]:
            context.user_data["title"] = text
        if context.user_data.get("choice") in [
            transcript["Serie"],
            transcript["Movie"],
        ]:
            logger.debug(
                f"user_data[choice] is {context.user_data['choice']}, skipping step of selecting movie/series"
            )
            return searchSerieMovie(update, context)
        else:
            reply_keyboard = [[transcript["Movie"], transcript["Serie"]]]
            markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
            update.message.reply_text(transcript["What is this?"], reply_markup=markup)
            return READ_CHOICE


def searchSerieMovie(update, context):
    title = context.user_data["title"]
    if context.user_data.get("title"):
        context.user_data.pop("title")
    if not context.user_data.get("choice"):
        choice = update.message.text
        context.user_data["choice"] = choice
    else:
        choice = context.user_data["choice"]
    context.user_data["position"] = 0

    service = getService(context)

    position = context.user_data["position"]

    searchResult = service.search(title)
    if searchResult:
        context.user_data["output"] = service.giveTitles(searchResult)

        reply_keyboard = [
            [transcript[choice.lower()]["Add"], transcript["Next result"]],
            [transcript["New"], transcript["Stop"]],
        ]
        markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["This"],
        )
        context.bot.sendPhoto(
            chat_id=update.effective_message.chat_id,
            photo=context.user_data["output"][position]["poster"],
        )
        text = f"{context.user_data['output'][position]['title']} ({context.user_data['output'][position]['year']})"
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=text, reply_markup=markup
        )
        return GIVE_OPTION
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=transcript["No results"],
        )
        clearUserData(context)
        return ConversationHandler.END


def nextOption(update, context):
    markup = None
    position = context.user_data["position"] + 1
    context.user_data["position"] = position

    choice = context.user_data["choice"]

    if position < len(context.user_data["output"]):
        reply_keyboard = [
            [transcript[choice.lower()]["Add"], transcript["Next result"]],
            [transcript["New"], transcript["Stop"]],
        ]
        markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)

        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["This"],
        )
        context.bot.sendPhoto(
            chat_id=update.effective_message.chat_id,
            photo=context.user_data["output"][position]["poster"],
        )
        text = (
            context.user_data["output"][position]["title"]
            + " ("
            + str(context.user_data["output"][position]["year"])
            + ")"
        )
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=text, reply_markup=markup
        )
        return GIVE_OPTION
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript["Last result"],
            reply_markup=markup,
        )
        clearUserData(context)
        return ConversationHandler.END


def pathSerieMovie(update, context):
    oddItem = None
    service = getService(context)
    paths = service.getRootFolders()
    context.user_data.update({"paths": [p["path"] for p in paths]})
    if len(paths) == 1:
        # There is only 1 path, so use it!
        logger.debug("Only found 1 path, so proceeding with that one...")
        context.user_data["path"] = paths[0]["path"]
        return languageSerieMovie(update, context)
    formattedPaths = [f"Path: {p['path']}" for p in paths]

    if len(paths) % 2 > 0:
        oddItem = formattedPaths.pop(-1)
    reply_keyboard = [
        [formattedPaths[i], formattedPaths[i + 1]]
        for i in range(0, len(formattedPaths), 2)
    ]
    if oddItem:
        reply_keyboard.append([oddItem])
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=transcript["Select a path"],
        reply_markup=markup,
    )
    return GIVE_PATHS


def languageSerieMovie(update, context):
    oddItem = None
    if not context.user_data.get("path"):
        # Path selection should be in the update message
        if update.message.text.replace("Path: ", "").strip() in context.user_data.get(
            "paths", {}
        ):
            context.user_data["path"] = update.message.text.replace(
                "Path: ", ""
            ).strip()
        else:
            logger.debug(
                f"Message text [{update.message.text.replace('Path: ', '').strip()}] doesn't match any of the paths. Sending paths for selection..."
            )
            return pathSerieMovie(update, context)

    service = getService(context)
    profiles = service.getProfiles()
    context.user_data.update({"profiles": profiles})
    formattedProfiles = [f"{profile['name']}" for profile in profiles]

    if len(profiles) % 2 > 0:
        oddItem = formattedProfiles.pop(-1)
    reply_keyboard = [
        [formattedProfiles[i], formattedProfiles[i + 1]]
        for i in range(0, len(formattedProfiles), 2)
    ]
    if oddItem:
        reply_keyboard.append([oddItem])
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=transcript["Select a profile"],
        reply_markup=markup,
    )
    return GIVE_PROFILES


def addSerieMovie(update, context):
    position = context.user_data["position"]
    choice = context.user_data["choice"]
    idnumber = context.user_data["output"][position]["id"]
    path = context.user_data["path"]

    if not context.user_data.get("profile"):
        # Path selection should be in the update message
        for profile in context.user_data.get("profiles"):
            if profile["name"] == update.message.text:
                context.user_data["profile"] = profile["id"]
                break
    if not context.user_data.get("profile"):
        logger.debug(
            f"Message text [{update.message.text}] doesn't match any of the profiles. Sending profiles for selection..."
        )
        return languageSerieMovie(update, context)

    profile = context.user_data["profile"]
    service = getService(context)

    if not service.inLibrary(idnumber):
        if service.addToLibrary(idnumber, path, profile):
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript[choice.lower()]["Success"],
            )
            with open(REQUESTS_PATH, "r") as json_file:
                requests_json = json.load(json_file)
                requests_json[idnumber] = update.message.chat.id
            with open(REQUESTS_PATH, "w") as json_file:
                json.dump(requests_json, json_file)
            clearUserData(context)
            return ConversationHandler.END
        else:
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript[choice.lower()]["Failed"],
            )
            clearUserData(context)
            return ConversationHandler.END
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["Exist"],
        )
        clearUserData(context)
        return ConversationHandler.END


def allSeries(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    else:
        result = sonarr.allSeries()
        string = ""
        for serie in result:
            string += "• " \
            + serie["title"] \
            + " (" \
            + str(serie["year"]) \
            + ")" \
            + "\n" \
            + "        status: " \
            + serie["status"] \
            + "\n" \
            + "        monitored: " \
            + str(serie["monitored"]).lower() \
            + "\n"
        
        #max length of a message is 4096 chars
        if len(string) <= 4096:
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=string,
            )
        #split string if longer then 4096 chars
        else: 
            neededSplits = math.ceil(len(string) / 4096)
            positionNewLine = []
            index = 0
            while index < len(string): #Get positions of newline, so that the split will happen after a newline
                i = string.find("\n", index)
                if i == -1:
                    return positionNewLine
                positionNewLine.append(i)
                index+=1

            #split string at newline closest to maxlength
            stringParts = []
            lastSplit = timesSplit = 0
            i = 4096
            while i > 0 and len(string)>4096: 
                if timesSplit < neededSplits:
                    if i+lastSplit in positionNewLine:
                        stringParts.append(string[0:i])
                        string = string[i+1:]
                        timesSplit+=1
                        lastSplit = i
                        i = 4096
                i-=1
            stringParts.append(string)

            #print every substring
            for subString in stringParts:
                context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=subString,
            )
        return ConversationHandler.END


def pourcentage(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    else:
        queue = radarr.get_queue_pourcentage()
        for title in queue:
            text = "{title} - {pourcent}%".format(title=title, pourcent=queue[title])
            context.bot.send_message(chat_id=update.effective_message.chat_id,
                                     text=text)
        queue = sonarr.get_queue_pourcentage()
        for title in queue:
            text = "{title} - {pourcent}%".format(title=title, pourcent=queue[title])
            context.bot.send_message(chat_id=update.effective_message.chat_id,
                                     text=text)
        return ConversationHandler.END


def chooseSerie(update, context):
    oddItem = None
    my_series = sonarr.allSeries()
    context.user_data.update({"my_series": my_series})

    formattedSeries = [f"{serie['title']}" for serie in my_series]

    if len(formattedSeries) % 2 > 0:
        oddItem = formattedSeries.pop(-1)
    reply_keyboard = [
        [formattedSeries[i], formattedSeries[i + 1]]
        for i in range(0, len(formattedSeries), 2)
    ]
    if oddItem:
        reply_keyboard.append([oddItem])
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=transcript["Select a serie"],
        reply_markup=markup,
    )
    return CHOOSE_SERIE


def chooseSeason(update, context):
    serieTitle = update.message.text
    my_series = context.user_data["my_series"]
    id = None
    seasonCount = None
    oddItem = None
    for serie in my_series:
        if serie["title"] == serieTitle:
            id = serie["id"]
            seasonCount = serie["seasonCount"]
            context.user_data.update({"serie_chosen_id": id})
            break
    if id and seasonCount:
        seasons = []
        for season in range(1, seasonCount + 1):
            seasons.append(f"Saison {season}")

        if len(seasons) % 2 > 0:
            oddItem = seasons.pop(-1)
        reply_keyboard = [
            [seasons[i], seasons[i + 1]]
            for i in range(0, len(seasons), 2)
        ]
        if oddItem:
            reply_keyboard.append([oddItem])
        markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript["Select a season"],
            reply_markup=markup,
        )
        return CHOOSE_SEASON
    return ConversationHandler.END


def searchSeason(update, context):
    try:
        season_chosen = update.message.text
        serie_chosen_id = context.user_data["serie_chosen_id"]
        seasonNumber = [int(s) for s in season_chosen.split() if s.isdigit()][0]
        if sonarr.searchSeason(serie_chosen_id, seasonNumber):
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript["serie"]["SeasonSuccess"],
            )
    except Exception:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript["serie"]["Failed"],
        )
    return ConversationHandler.END



def getService(context):
    if context.user_data.get("choice") == transcript["Serie"]:
        return sonarr
    elif context.user_data.get("choice") == transcript["Movie"]:
        return radarr
    else:
        raise ValueError(
            f"Cannot determine service based on unknown or missing choice: {context.user_data.get('choice')}."
        )


def clearUserData(context):
    logger.debug(
        "Removing choice, title, position, paths, and output from context.user_data..."
    )
    for x in [
        x
        for x in ["choice", "title", "position", "output", "paths", "path"]
        if x in context.user_data.keys()
    ]:
        context.user_data.pop(x)

APP = Flask(__name__)

def flask_start():
    APP.run("0.0.0.0", port=6200)

@APP.route('/', methods=['GET', 'POST'])
def notify_chat():
    data = request.json
    print(data)
    id = None
    try:
        id = str(data['movie']['tmdbId'])
        title = data['movie']['title']
        quality = data['release']['quality']
        size = data['release']['size'] / 1024 / 1024 / 1024
        event = data['eventType']
    except KeyError:
        print("key error")
        try:
            id = str(data['serie']['tvdbId'])
        except KeyError:
            return "Not OK"
    if not id:
        return "Not OK"
    with open(REQUESTS_PATH, "r") as json_file:
        print(f"{title} - {quality} - {size} is {event}")
        request_json = json.load(json_file)
        try:
            chat_id = request_json[id]
        except KeyError:
            return "Not OK"
        text = f"{title} - {quality} - {str(round(size, 2))}Gb is {event}"
        data_to_send = {'chat_id': {chat_id}, 'text': text}
        requests.post(f'https://api.telegram.org/bot{config["telegram"]["token"]}/sendMessage', data_to_send)
    return "hi"

if __name__ == "__main__":
    flask_thread = threading.Thread(target=flask_start)
    flask_thread.start()
    main()
