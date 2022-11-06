# This class is responsible for handling all asynchronous Logz.io's
# communication
import sys
import json

from time import sleep
from datetime import datetime
from threading import Thread, enumerate
from urllib import response


import requests

from .logger import get_logger
from .logger import get_stdout_logger

from jsonrpcclient import request
import requests, json, os

if sys.version[0] == '2':
    import Queue as queue
else:
    import queue as queue

MAX_BULK_SIZE_IN_BYTES = 1 * 1024 * 1024  # 1 MB


def backup_logs(logs, logger):
    timestamp = datetime.now().strftime('%d%m%Y-%H%M%S')
    logger.info(
        'Backing up your logs to swing-failures-%s.txt', timestamp)
    with open('swing-failures-{}.txt'.format(timestamp), 'a') as f:
        f.writelines('\n'.join(logs))


class LogzioSender:
    def __init__(self,
                 token, url='https://listener.logz.io:8071',
                 logs_drain_timeout=5,
                 debug=False,
                 backup_logs=True,
                 network_timeout=10.0,
                 number_of_retries=4,
                 retry_timeout=2):
        self.token = token
        self.url = '{}/?token={}'.format(url, token)
        self.logs_drain_timeout = logs_drain_timeout
        self.stdout_logger = get_stdout_logger(debug)
        self.backup_logs = backup_logs
        self.network_timeout = network_timeout
        self.requests_session = requests.Session()
        self.number_of_retries = number_of_retries
        self.retry_timeout = retry_timeout

        # Function to see if the main thread is alive
        self.is_main_thread_active = lambda: any(
            (i.name == 'MainThread') and i.is_alive() for i in enumerate())

        # Create a queue to hold logs
        self.queue = queue.Queue()
        self._initialize_sending_thread()

    def __del__(self):
        del self.stdout_logger
        del self.backup_logs
        del self.queue

    def _initialize_sending_thread(self):
        self.sending_thread = Thread(target=self._drain_queue)
        self.sending_thread.daemon = False
        self.sending_thread.name = 'logzio-sending-thread'
        self.sending_thread.start()

    def append(self, logs_message):
        if not self.sending_thread.is_alive():
            self._initialize_sending_thread()

        # Queue lib is thread safe, no issue here
        self.queue.put(json.dumps(logs_message))

    def flush(self):
        #self._flush_queue()
        self._flush_queue_rpc()

    def _drain_queue(self):
        last_try = False

        while not last_try:
            # If main is exited, we should run one last time and try to remove
            # all logs
            if not self.is_main_thread_active():
                self.stdout_logger.debug(
                    'Identified quit of main thread, sending logs one '
                    'last time')
                last_try = True

            try:
                self._flush_queue_rpc()
            except Exception as e:
                self.stdout_logger.debug(
                    'Unexpected exception while draining queue to swing, '
                    'swallowing. Exception: %s', e)

            if not last_try:
                sleep(self.logs_drain_timeout)

    def _flush_queue_rpc(self):
        while not self.queue.empty():
            logs_list = self._get_messages_up_to_max_allowed_size()
            self.stdout_logger.debug(
                'Starting to drain %s logs to swing', len(logs_list))

            # Not configurable from the outside
            sleep_between_retries = self.retry_timeout
            self.number_of_retries = self.number_of_retries

            should_backup_to_disk = True
            headers = {"Content-type": "application/json"}

            
            for current_try in range(self.number_of_retries):
                should_retry = False
                try:
                    
                    response = CreateRecords(token=self.token,records=logs_list)
                    if response['error']:
                        should_retry = True
                    else:
                        self.stdout_logger.debug(
                            'Successfully sent bulk of %s logs to '
                            'swing', len(logs_list))
                        should_backup_to_disk = False
                        break
                except Exception as e:
                    self.stdout_logger.warning(
                        'Got exception while sending logs to swing, '
                        'Try (%s/%s). Message: %s',
                        current_try + 1, self.number_of_retries, e)
                    should_retry = True

                if should_retry:
                    sleep(sleep_between_retries)

            if should_backup_to_disk and self.backup_logs:
                # Write to file
                self.stdout_logger.error(
                    'Could not send logs to swing after %s tries, '
                    'backing up to local file system', self.number_of_retries)
                backup_logs(logs_list, self.stdout_logger)

            del logs_list
            
    def _flush_queue(self):
        # Sending logs until queue is empty
        while not self.queue.empty():
            logs_list = self._get_messages_up_to_max_allowed_size()
            self.stdout_logger.debug(
                'Starting to drain %s logs to Logz.io', len(logs_list))

            # Not configurable from the outside
            sleep_between_retries = self.retry_timeout
            self.number_of_retries = self.number_of_retries

            should_backup_to_disk = True
            headers = {"Content-type": "text/plain"}

            for current_try in range(self.number_of_retries):
                should_retry = False
                try:
                    response = self.requests_session.post(
                        self.url, headers=headers, data='\n'.join(logs_list),
                        timeout=self.network_timeout)
                    if response.status_code != 200:
                        if response.status_code == 400:
                            self.stdout_logger.info(
                                'Got 400 code from Logz.io. This means that '
                                'some of your logs are too big, or badly '
                                'formatted. response: %s', response.text)
                            should_backup_to_disk = False
                            break

                        if response.status_code == 401:
                            self.stdout_logger.info(
                                'You are not authorized with Logz.io! Token '
                                'OK? dropping logs...')
                            should_backup_to_disk = False
                            break
                        else:
                            self.stdout_logger.info(
                                'Got %s while sending logs to Logz.io, '
                                'Try (%s/%s). Response: %s',
                                response.status_code,
                                current_try + 1,
                                self.number_of_retries,
                                response.text)
                            should_retry = True
                    else:
                        self.stdout_logger.debug(
                            'Successfully sent bulk of %s logs to '
                            'Logz.io!', len(logs_list))
                        should_backup_to_disk = False
                        break
                except Exception as e:
                    self.stdout_logger.warning(
                        'Got exception while sending logs to Logz.io, '
                        'Try (%s/%s). Message: %s',
                        current_try + 1, self.number_of_retries, e)
                    should_retry = True

                if should_retry:
                    sleep(sleep_between_retries)

            if should_backup_to_disk and self.backup_logs:
                # Write to file
                self.stdout_logger.error(
                    'Could not send logs to Logz.io after %s tries, '
                    'backing up to local file system', self.number_of_retries)
                backup_logs(logs_list, self.stdout_logger)

            del logs_list

    def _get_messages_up_to_max_allowed_size(self):
        logs_list = []
        current_size = 0
        while not self.queue.empty():
            current_log = self.queue.get()
            try:
                current_size += sys.getsizeof(current_log)
            except TypeError:
                # pypy do not support sys.getsizeof
                current_size += len(current_log) * 4

            logs_list.append(current_log)
            if current_size >= MAX_BULK_SIZE_IN_BYTES:
                break
        return logs_list


def CreateRecords(token:str, records: list[dict]):
    param = {"token": token,"records": []}
    #os.getenv("swingtoken")

    for record in records: 
        jsonRecord = json.loads(record)
        swingRecord = {}
        swingRecord["timestamp"] = jsonRecord["@timestamp"]
        swingRecord["message"] = jsonRecord["message"]
        swingRecord["stacktrace"] = jsonRecord["path_name"]
        swingRecord["logger"] = jsonRecord["logger"]
        swingRecord["linenum"] = jsonRecord["line_number"]
        swingRecord["function"] = jsonRecord["type"]
        swingRecord["level"] = jsonRecord["log_level"]
        swingRecord["process"] = jsonRecord["process"]

        param['records'].append(swingRecord)
    
    
    res = requests.post("http://localhost:8081", json=request("records.create.many", params=param), 
                    headers={"Content-type": "application/json"})
    return res.json()