import os
import json
from json import JSONEncoder
from datamodel import *
from trader import Trader
import jsonpickle

trader = Trader()


def lambda_handler(event, context):
    try:
        current_bid = trader.bid()
    except:
        current_bid = 0
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "bid": current_bid
        }, cls=ProsperityEncoder)
    }
