import json
import time
from ha_logger import hybridlogger

import urllib.parse
import requests
from omnik.plugin_output import Plugin


class pvoutput(Plugin):

    def __init__(self):
        super().__init__()
        self.name = 'pvoutput'
        self.description = 'Write output to PVOutput'
        # tz = self.config.get('default', 'timezone',
        #                      fallback='Europe/Amsterdam')
        # self.timezone = pytz.timezone(tz)

    def get_weather(self):
        try:
            if 'weather' not in self.cache:
                self.logger.debug('[cache miss] Fetching weather data')
                url = "https://{endpoint}/data/2.5/weather?lon={lon}&lat={lat}&units={units}&APPID={api_key}".format(
                    endpoint=self.config.get('openweathermap', 'endpoint', fallback='api.openweathermap.org'),
                    lat=self.config.get('openweathermap', 'lat'),
                    lon=self.config.get('openweathermap', 'lon'),
                    units=self.config.get(
                        'openweathermap', 'units', fallback='metric'),
                    api_key=self.config.get('openweathermap', 'api_key'),
                )

                res = requests.get(url)

                res.raise_for_status()

                self.cache['weather'] = res.json()

            return self.cache['weather']

        except requests.exceptions.HTTPError as e:
            hybridlogger.ha_log(self.logger, self.hass_api, "ERROR", 'Unable to get weather data. [{0}]: {1}'.format(
                                type(e).__name__, str(e)))
            raise e

    def _get_temperature(self, msg, data):
        if self.config.getboolean('pvoutput', 'use_temperature', fallback=False):
            if self.config.getboolean('pvoutput', 'use_inverter_temperature', fallback=False) and \
                    ('inverter_temperature' in msg):
                data['v5'] = msg['inverter_temperature']
            else:
                weather = self.get_weather()

                data['v5'] = weather['main']['temp']

    def _get_voltage(self, msg, data):
        voltage_field = self.config.get('pvoutput', 'publish_voltage', fallback=None)
        if voltage_field:
            if voltage_field in msg:
                data['v6'] = msg[voltage_field]

    def process(self, **args):
        """
        Send data to pvoutput
        """
        try:
            msg = args['msg']
            reporttime = time.localtime(msg['last_update'])

            self.logger.debug(json.dumps(msg, indent=2))

            if not self.config.has_option('pvoutput', 'sys_id') or not self.config.has_option('pvoutput', 'api_key'):
                hybridlogger.ha_log(self.logger, self.hass_api, "ERROR",
                                    f'[{__name__}] No api_key and/or sys_id found in configuration')
                return

            headers = {
                "X-Pvoutput-Apikey": self.config.get('pvoutput', 'api_key'),
                "X-Pvoutput-SystemId": str(self.config.get('pvoutput', 'sys_id')),
                "Content-type": "application/x-www-form-urlencoded",
                "Accept": "text/plain"
            }

            # see: https://pvoutput.org/help.html
            # see: https://pvoutput.org/help.html#api-addstatus
            data = {
                'd': time.strftime('%Y%m%d', reporttime),
                't': time.strftime('%H:%M', reporttime),
                'v1': (msg['today_energy'] * 1000.0),
                'v2': msg['current_power'],
                'c1': 0
            }

            # Publish inverter temperature is available or use the temperature from openweather
            self._get_temperature(msg, data)

            # Publish voltage (if available)
            self._get_voltage(msg, data)

            encoded = urllib.parse.urlencode(data)

            self.logger.debug(json.dumps(data, indent=2))

            r = requests.post(
                "http://pvoutput.org/service/r2/addstatus.jsp", data=encoded, headers=headers)

            r.raise_for_status()

        except requests.exceptions.RequestException as err:
            hybridlogger.ha_log(self.logger, self.hass_api, "WARNING", f"Unhandled request error: {err}")
        except requests.exceptions.HTTPError as errh:
            hybridlogger.ha_log(self.logger, self.hass_api, "WARNING", f"Http error: {errh}")
        except requests.exceptions.ConnectionError as errc:
            hybridlogger.ha_log(self.logger, self.hass_api, "WARNING", f"Connection error: {errc}")
        except requests.exceptions.Timeout as errt:
            hybridlogger.ha_log(self.logger, self.hass_api, "WARNING", f"Timeout error: {errt}")
        except Exception as e:
            hybridlogger.ha_log(self.logger, self.hass_api, "ERROR", e)