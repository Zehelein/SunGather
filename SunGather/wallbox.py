#!/usr/bin/python3

from SungrowClient import SungrowClient
from version import __version__

import importlib
import logging
import logging.handlers
import sys
import getopt
import yaml
import time

def main():
    configfilename = 'config.yaml'
    registersfilename = 'registers-wallbox.yaml'
    logfolder = ''

    try:
        opts, args = getopt.getopt(sys.argv[1:],"hc:r:l:v:", "runonce")
    except getopt.GetoptError:
        sys.exit(f'No options passed via command line, use -h to see all options')


    for opt, arg in opts:
        if opt == '-h':
            print(f'\nSunGather {__version__}')
            print(f'\nhttps://sungather.app')
            print(f'usage: python3 wallbox.py [options]')
            print(f'\nCommandling arguments override any config file settings')
            print(f'Options and arguments:')
            print(f'-c config.yaml             : Specify config file.')
            print(f'-r registers-file.yaml     : Specify registers file.')
            print(f'-l /logs/                  : Specify folder to store logs.')
            print(f'-v 30                      : Logging Level, 10 = Debug, 20 = Info, 30 = Warning (default), 40 = Error')
            print(f'--runonce                  : Run once then exit')
            print(f'-h                         : print this help message and exit (also --help)')
            print(f'\nExample:')
            print(f'python3 wallbox.py -c /full/path/config.yaml\n')
            sys.exit()
        elif opt == '-c':
            configfilename = arg
        elif opt == '-r':
            registersfilename = arg
        elif opt == '-l':
            logfolder = arg    
        elif opt  == '-v':
            if arg.isnumeric():
                if int(arg) >= 0 and int(arg) <= 50:
                    loglevel = int(arg)
                else:
                    logging.error(f"Valid verbose options: 10 = Debug, 20 = Info, 30 = Warning (default), 40 = Error")
                    sys.exit(2)        
            else:
                logging.error(f"Valid verbose options: 10 = Debug, 20 = Info, 30 = Warning (default), 40 = Error")
                sys.exit(2) 
        elif opt == '--runonce':
            runonce = True

    logging.info(f'Starting SunGather {__version__}')
    logging.info(f'Need Help? https://github.com/bohdan-s/SunGather')
    logging.info(f'NEW HomeAssistant Add-on: https://github.com/bohdan-s/hassio-repository')

    try:
        configfile = yaml.safe_load(open(configfilename, encoding="utf-8"))
        logging.info(f"Loaded config: {configfilename}")
    except Exception as err:
        logging.error(f"Failed: Loading config: {configfilename} \n\t\t\t     {err}")
        sys.exit(1)
    if not configfile.get('wallbox'):
        logging.error(f"Failed Loading config, missing wallbox settings")
        sys.exit(f"Failed Loading config, missing wallbox settings")   

    try:
        registersfile = yaml.safe_load(open(registersfilename, encoding="utf-8"))
        logging.info(f"Loaded registers: {registersfilename}")
        logging.info(f"Registers file version: {registersfile.get('version','UNKNOWN')}")
    except Exception as err:
        logging.error(f"Failed: Loading registers: {registersfilename}  {err}")
        sys.exit(f"Failed: Loading registers: {registersfilename} {err}")
   
    config_wallbox = {
        "host": configfile['wallbox'].get('host',None),
        "port": configfile['wallbox'].get('port',502),
        "timeout": configfile['wallbox'].get('timeout',10),
        "retries": configfile['wallbox'].get('retries',3),
        "slave": configfile['wallbox'].get('slave',0x02),
        "scan_interval": configfile['wallbox'].get('scan_interval',30),
        "connection": configfile['wallbox'].get('connection',"modbus"),
        "model": configfile['wallbox'].get('model',None),
        "smart_meter": configfile['wallbox'].get('smart_meter',False),
        "use_local_time": configfile['wallbox'].get('use_local_time',False),
        "log_console": configfile['wallbox'].get('log_console','WARNING'),
        "log_file": configfile['wallbox'].get('log_file','OFF'),
        "level": configfile['wallbox'].get('level',1)
    }

    if 'loglevel' in locals():
        logger.handlers[0].setLevel(loglevel)
    else:
        logger.handlers[0].setLevel(config_wallbox['log_console'])

    if not config_wallbox['log_file'] == "OFF":
        if config_wallbox['log_file'] == "DEBUG" or config_wallbox['log_file'] == "INFO" or config_wallbox['log_file'] == "WARNING" or config_wallbox['log_file'] == "ERROR":
            logfile = logfolder + "SunGather.log"
            fh = logging.handlers.RotatingFileHandler(logfile, mode='w', encoding='utf-8', maxBytes=10485760, backupCount=10) # Log 10mb files, 10 x files = 100mb
            fh.formatter = logger.handlers[0].formatter
            fh.setLevel(config_wallbox['log_file'])
            logger.addHandler(fh)
        else:
            logging.warning(f"log_file: Valid options are: DEBUG, INFO, WARNING, ERROR and OFF")

    logging.info(f"Logging to console set to: {logging.getLevelName(logger.handlers[0].level)}")
    if logger.handlers.__len__() == 3:
        logging.info(f"Logging to file set to: {logging.getLevelName(logger.handlers[2].level)}")
    
    logging.debug(f'Wallbox Config Loaded: {config_wallbox}')    

    if config_wallbox.get('host'):
        wallbox = SungrowClient.SungrowClient(config_wallbox)
    else:
        logging.error(f"Error: host option in config is required")
        sys.exit("Error: host option in config is required")

    if not wallbox.checkConnection():
        logging.error(f"Error: Connection to wallbox failed: {config_wallbox.get('host')}:{config_wallbox.get('port')}")
        sys.exit(f"Error: Connection to wallbox failed: {config_wallbox.get('host')}:{config_wallbox.get('port')}")       

    wallbox.configure_registers(registersfile)
    if not wallbox.inverter_config['connection'] == "http": wallbox.close()
    
    # Now we know the wallbox is working, lets load the exports
    exports = []
    if configfile.get('exports'):
        for export in configfile.get('exports'):
            try:
                if export.get('enabled', False):
                    export_load = importlib.import_module("exports." + export.get('name'))
                    logging.info(f"Loading Export: exports {export.get('name')}")
                    exports.append(getattr(export_load, "export_" + export.get('name'))())
                    retval = exports[-1].configure(export, wallbox)
            except Exception as err:
                logging.error(f"Failed loading export: {err}" +
                            f"\n\t\t\t     Please make sure {export.get('name')}.py exists in the exports folder")

    scan_interval = config_wallbox.get('scan_interval')

    # Core polling loop
    while True:
        loop_start = time.perf_counter()

        wallbox.checkConnection()

        # Scrape the wallbox
        try:
            success = wallbox.scrape()
        except Exception as e:
            logging.exception(f"Failed to scrape: {e}")
            success = False

        if(success):
            for export in exports:
                export.publish(wallbox)
            if not wallbox.inverter_config['connection'] == "http": wallbox.close()
        else:
            wallbox.disconnect()
            logging.warning(f"Data collection failed, skipped exporting data. Retying in {scan_interval} secs")

        loop_end = time.perf_counter()
        process_time = round(loop_end - loop_start, 2)
        logging.debug(f'Processing Time: {process_time} secs')

        if 'runonce' in locals():
            sys.exit(0)
        
        # Sleep until the next scan
        if scan_interval - process_time <= 1:
            logging.warning(f"SunGather is taking {process_time} to process, which is longer than interval {scan_interval}, Please increase scan interval")
            time.sleep(process_time)
        else:
            logging.info(f'Next scrape in {int(scan_interval - process_time)} secs')
            time.sleep(scan_interval - process_time)    

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger('')
ch = logging.StreamHandler()
ch.setLevel(logging.WARNING)
logger.addHandler(ch)

if __name__== "__main__":
    main()

sys.exit()
