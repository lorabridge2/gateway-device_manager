#!/usr/bin/env python3
# -*- coding=utf-8 -*-

from enum import IntEnum
import paho.mqtt.client as mqtt
import json
import os
import sys
import redis
import logging

import redis.asyncio
import redis.client
import redis.utils
import base64


def get_fileenv(var: str):
    """Tries to read the provided env var name + _FILE first and read the file at the path of env var value.
    If that fails, it looks at /run/secrets/<env var>, otherwise uses the env var itself.
    Args:
        var (str): Name of the provided environment variable.

    Returns:
        Content of the environment variable file if exists, or the value of the environment variable.
        None if the environment variable does not exist.
    """
    if path := os.environ.get(var + "_FILE"):
        with open(path) as file:
            return file.read().strip()
    else:
        try:
            with open(os.path.join("run", "secrets", var.lower())) as file:
                return file.read().strip()
        except IOError:
            # mongo username needs to be string and not empty (fix for sphinx)
            if "sphinx" in sys.modules:
                return os.environ.get(var, "fail")
            else:
                return os.environ.get(var)


MQTT_HOST = os.environ.get("DEV_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("DEV_MQTT_PORT", 1883))
MQTT_USERNAME = get_fileenv("DEV_MQTT_USERNAME") or "lorabridge"
MQTT_PASSWORD = get_fileenv("DEV_MQTT_PASSWORD") or "lorabridge"
DEV_MAN_TOPIC = os.environ.get("DEV_MAN_TOPIC", "devicemanager")
REDIS_HOST = os.environ.get("DEV_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("DEV_REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("DEV_REDIS_DB", 0))
DISCOVERY_TOPIC = os.environ.get("DEV_DISCOVERY_TOPIC", "lorabridge/discovery")
STATE_TOPIC = os.environ.get("DEV_STATE_TOPIC", "lorabridge/state")
DEV_EUI = os.environ.get("DEV_EUI").removeprefix(r"\x")
APP_ID = None
with open(f"/device/{DEV_EUI.lower()}.json") as dfile:
    APP_ID = json.loads(dfile.read())["application_id"]

REDIS_SEPARATOR = ":"
REDIS_PREFIX = "lorabridge:devman"
REDIS_LB_INDEX = "index:lb"
REDIS_IEEE_INDEX = "index:ieee"
REDIS_DEV_NAME = "device:name"
REDIS_DEV_ATTRS = "device:attributes"
REDIS_DEV_DATA = "device:data"
REDIS_DEV_NOTIFICATION = "device:notification"


class action_bytes(IntEnum):
    REMOVE_NODE = 0
    ADD_NODE = 1
    ADD_DEVICE = 2
    PARAMETER_UPDATE = 3
    CONNECT_NODE = 4
    DISCONNECT_NODE = 5
    ENABLE_FLOW = 6
    DISABLE_FLOW = 7
    TIME_SYNC_RESPONSE = 8
    ADD_FLOW = 9
    FLOW_COMPLETE = 10
    REMOVE_FLOW = 11
    UPLOAD_FLOW = 12
    GET_DEVICES = 13


def send_commands(commands, client):
    msgs = [
        {
            "topic": f"application/{APP_ID}/device/{DEV_EUI}/command/down",
            "payload": json.dumps(
                {
                    "confirmed": True,
                    "fPort": 10,
                    "devEui": DEV_EUI,
                    "data": base64.b64encode(bytes(cmd)).decode(),
                }
            ),
        }
        for cmd in commands
    ]
    for msg in msgs:
        client.publish(msg["topic"], msg["payload"])


# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    logging.info("Connected with result code " + str(rc))
    send_commands([[action_bytes.GET_DEVICES, 0]], client)
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe(userdata["topic"] + "/#")


# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    rclient: redis.Redis = userdata["r_client"]
    data = json.loads(msg.payload)
    # store device infos in redis
    match data["type"]:
        case "name":
            rclient.hset(
                REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_LB_INDEX]), data["lb_id"], data["ieee_id"]
            )
            rclient.hset(
                REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_IEEE_INDEX]),
                data["ieee_id"],
                data["lb_id"],
            )
            rclient.set(
                REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_NAME, str(data["lb_id"])]),
                data["name"],
            )
        case "attributes":
            print(data["attributes"])
            if data["attributes"]:
                rclient.sadd(
                    REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_ATTRS, str(data["lb_id"])]),
                    *data["attributes"],
                )
        case "data":
            if lb_id := rclient.hget(
                REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_IEEE_INDEX]), data["ieee_id"]
            ):
                rclient.hset(
                    REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_DATA, str(lb_id)]),
                    mapping={k: str(v) if type(v) == bool else v for k, v in data["data"].items()},
                )

    # send data to plugins via mqtt
    match data["type"]:
        case "name" | "attributes":
            if (
                (
                    ieee := rclient.hget(
                        REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_LB_INDEX]), data["lb_id"]
                    )
                )
                and (
                    name := rclient.get(
                        REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_NAME, str(data["lb_id"])])
                    )
                )
                and (
                    attributes := rclient.smembers(
                        REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_ATTRS, str(data["lb_id"])])
                    )
                )
            ):
                # keys = (
                #     REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_ATTRS, data["lb_id"]]),
                #     REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_NAME, data["lb_id"]]),
                # )
                # if rclient.exists(*keys) == len(keys) and rclient.hexists(
                #     REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_LB_INDEX]), data["lb_id"]
                # ):
                client.publish(
                    DISCOVERY_TOPIC,
                    json.dumps(
                        {
                            "id": data["lb_id"],
                            "ieee_id": ieee,
                            "lb_name": name,
                            "measurement": list(attributes),
                            "value": {x: None for x in attributes},  # backwards compatibility
                        }
                    ),
                )
                rclient.publish(
                    REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_DEV_NOTIFICATION]),
                    json.dumps(
                        {
                            "lb_id": data["lb_id"],
                            "ieee": ieee,
                            "name": name,
                            "attributes": list(attributes),
                        }
                    ),
                )
        case "data":
            if lb_id := rclient.hget(
                REDIS_SEPARATOR.join([REDIS_PREFIX, REDIS_LB_INDEX]), data["ieee_id"]
            ):
                client.publish(
                    STATE_TOPIC,
                    json.dumps(
                        {
                            "id": lb_id,
                            "value": data["data"],
                            "ieee_id": data["ieee_id"],
                            "measurement": [],  # backwards compatibility
                        }
                    ),
                )

    # if not rclient.exists(
    #     (
    #         rkey := REDIS_SEPARATOR.join(
    #             [REDIS_PREFIX, (ieee := msg.topic.removeprefix(DEV_MAN_TOPIC + "/"))]
    #         )
    #     )
    # ):
    #     index = rclient.incr(REDIS_SEPARATOR.join([REDIS_PREFIX, "dev_index"]))
    #     dev_data = {"ieee": ieee, "id": index, "measurement": json.dumps(list(data.keys()))}
    #     rclient.hset(rkey, mapping=dev_data)
    #     rclient.sadd(REDIS_SEPARATOR.join([REDIS_PREFIX, "devices"]), rkey)
    #     dev_data["measurement"] = json.loads(dev_data["measurement"])
    #     dev_data.update({"value": data})
    #     client.publish(DISCOVERY_TOPIC, json.dumps(dev_data))
    #     client.publish(STATE_TOPIC, json.dumps(dev_data))
    #     # discovery
    # else:
    #     # state update
    #     dev_data = rclient.hgetall(rkey)
    #     str_data = json.dumps(list(data.keys()))
    #     if dev_data["measurement"] != str_data:
    #         dev_data["measurement"] = str_data
    #         rclient.hset(rkey, mapping=dev_data)
    #     dev_data["measurement"] = json.loads(dev_data["measurement"])
    #     dev_data.update({"value": data})
    #     if dev_data["measurement"] != str_data:
    #         client.publish(DISCOVERY_TOPIC, json.dumps(dev_data))
    #     client.publish(STATE_TOPIC, json.dumps(dev_data))


def main():
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.user_data_set({"topic": DEV_MAN_TOPIC})

    r_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    client.user_data_set({"r_client": r_client, "topic": DEV_MAN_TOPIC})

    # Blocking call that processes network traffic, dispatches callbacks and
    # handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a
    # manual interface.
    client.loop_forever()


if __name__ == "__main__":
    main()
