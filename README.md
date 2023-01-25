# Gateway Device Manager

This repository is part of the [LoRaBridge](https://github.com/lorabridge/lorabridge) project.
It provides the docker image for the Device Management used on our gateway device.

The Device Manager is a self-provided Python3 application keeping track of the discovered devices via the Redis server. 
It publishes MQTT messages on the Mosquitto server for device discovery events and status (data) updates. 
These messages are picked up by the HA Integration service.

## Environment Variables

- `DEV_MQTT_HOST`: IP or hostname of MQTT host
- `DEV_MQTT_PORT`: Port used by MQTT
- `DEV_MQTT_USERNAME`: MQTT username if used (can be a file as well)
- `DEV_MQTT_PASSWORD`: MQTT password if used (can be a file as well)
- `DEV_DEV_MAN_TOPIC`: MQTT topic used by the converter to address this device manager (default: `devicemanager`)
- `DEV_REDIS_HOST`: IP or hostname of Redis host
- `DEV_REDIS_PORT`: Port used by Redis
- `DEV_REDIS_DB`: Number of the database used inside Redis
- `DEV_DISCOVERY_TOPIC`: MQTT topic used for announcing newly discovered devices (default: `lorabridge/discovery`)
- `DEV_STATE_TOPIC`: MQTT topic used for announcing states (measurements) of devices (default: `lorabridge/state`)

## License

All the LoRaBridge software components and the documentation are licensed under GNU General Public License 3.0.

## Acknowledgements

The financial support from Internetstiftung/Netidee is gratefully acknowledged. The mission of Netidee is to support development of open-source tools for more accessible and versatile use of the Internet in Austria.
