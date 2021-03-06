#!/usr/bin/env python

########################################################################
# Date : Apr 4th, 2013
# Author  : Nicholas Scott ( scot0357 at gmail.com )
# Help : scot0357 at gmail.com
# Licence : GPL - http://www.fsf.org/licenses/gpl.txt
# TODO : Bug Testing, Feature Adding
# Changelog:
# 1.1.0 -   Fixed port bug allowing for non default ports | Thanks CBTSDon
#           Added mode error checking which caused non-graceful exit | Thanks mike from austria
# 1.2.0 -   Added ability to monitor instances
#           Added check to see if pymssql is installed
# 1.3.0 -   Added ability specify MSSQL instances
# 2.0.0 -   Complete Revamp/Rewrite based on the server version of this plugin
# 2.0.1 -   Fixed bug where temp file was named same as other for host and numbers
#           were coming back bogus.
########################################################################

import pymssql
import time
import sys
import tempfile
try:
    import cPickle as pickle
except:
    import pickle
from optparse import OptionParser, OptionGroup

BASE_QUERY = "SELECT cntr_value FROM sys.dm_os_performance_counters WHERE counter_name='%s' AND instance_name='%%s';"
DIVI_QUERY = "SELECT cntr_value FROM sys.dm_os_performance_counters WHERE counter_name LIKE '%s%%%%' AND instance_name='%%s';"
LISTDB_QUERY = "SELECT NAME FROM sys.sysdatabases;"

MODES     = {
    
    'logcachehit'       : { 'help'      : 'Log Cache Hit Ratio',
                            'stdout'    : 'Log Cache Hit Ratio is %s%%',
                            'label'     : 'log_cache_hit_ratio',
                            'unit'      : '%',
                            'query'     : DIVI_QUERY % 'Log Cache Hit Ratio',
                            'type'      : 'divide',
                            'modifier'  : 100,
                            },
    
    'activetrans'       : { 'help'      : 'Active Transactions',
                            'stdout'    : 'Active Transactions is %s',
                            'label'     : 'log_file_usage',
                            'unit'      : '',
                            'query'     : BASE_QUERY % 'Active Transactions',
                            'type'      : 'standard',
                            },
    
    'logflushes'         : { 'help'      : 'Log Flushes Per Second',
                            'stdout'    : 'Log Flushes Per Second is %s/sec',
                            'label'     : 'log_flushes_per_sec',
                            'query'     : BASE_QUERY % 'Log Flushes/sec',
                            'type'      : 'delta'
                            },
    
    'logfileusage'      : { 'help'      : 'Log File Usage',
                            'stdout'    : 'Log File Usage is %s%%',
                            'label'     : 'log_file_usage',
                            'unit'      : '%',
                            'query'     : BASE_QUERY % 'Percent Log Used',
                            'type'      : 'standard',
                            },
    
    'transpec'          : { 'help'      : 'Transactions Per Second',
                            'stdout'    : 'Transactions Per Second is %s/sec',
                            'label'     : 'transactions_per_sec',
                            'query'     : BASE_QUERY % 'Transactions/sec',
                            'type'      : 'delta'
                            },
    
    'loggrowths'        : { 'help'      : 'Log Growths',
                            'stdout'    : 'Log Growths is %s',
                            'label'     : 'log_growths',
                            'query'     : BASE_QUERY % 'Log Growths',
                            'type'      : 'standard'
                            },
    
    'logshrinks'        : { 'help'      : 'Log Shrinks',
                            'stdout'    : 'Log Shrinks is %s',
                            'label'     : 'log_shrinks',
                            'query'     : BASE_QUERY % 'Log Shrinks',
                            'type'      : 'standard'
                            },
    
    'logtruncs'         : { 'help'      : 'Log Truncations',
                            'stdout'    : 'Log Truncations is %s',
                            'label'     : 'log_truncations',
                            'query'     : BASE_QUERY % 'Log Truncations',
                            'type'      : 'standard'
                            },
    
    'logwait'           : { 'help'      : 'Log Flush Wait Time',
                            'stdout'    : 'Log Flush Wait Time is %sms',
                            'label'     : 'log_wait_time',
                            'unit'      : 'ms',
                            'query'     : BASE_QUERY % 'Log Flush Wait Time',
                            'type'      : 'standard'
                            },
    
    'datasize'          : { 'help'      : 'Database Size',
                            'stdout'    : 'Database size is %sKB',
                            'label'     : 'database_size',
                            'unit'      : 'KB',
                            'query'     : BASE_QUERY % 'Data File(s) Size (KB)',
                            'type'      : 'standard'
                            },

    'logsize'           : { 'help'      : 'Log File Size',
                            'stdout'    : 'Log file size is %sKB',
                            'label'     : 'logfile_size',
                            'unit'      : 'KB',
                            'query'     : BASE_QUERY % 'Log File(s) Size (KB)',
                            'type'      : 'standard'
                            },
   
    'time2connect'      : { 'help'      : 'Time to connect to the database.' },
    
    'test'              : { 'help'      : 'Run tests of all queries against the database.' },
}

STDOUT_PREFIX = {
    0 : 'OK: ',
    1 : 'WARNING: ',
    2 : 'CRITICAL: ',
}

DATASIZE_UNIT = {
    'B'  : 1024,
    'KB' : 1,
    'MB' : 1.0/1024,
    'GB' : 1.0/(1024 * 1024),
    'TB' : 1.0/(1024 * 1024 * 1024),
}

def return_nagios(options, stdout='', result='', unit='', label=''):
    if is_within_range(options.critical, result):
        code = 2
    elif is_within_range(options.warning, result):
        code = 1
    else:
        code = 0
    strresult = str(result)
    stdout = stdout % (strresult)
    stdout = "%s%s" % (STDOUT_PREFIX[code], stdout)
    if not options.no_perfdata:
        stdout = "%s|'%s'=%s%s;%s;%s;;" % (stdout, label, strresult, unit, options.warning or '', options.critical or '')
    raise NagiosReturn(stdout, code)

class NagiosReturn(Exception):
    
    def __init__(self, message, code):
        self.message = message
        self.code = code

class MSSQLQuery(object):
    
    def __init__(self, query, options, label='', unit='', stdout='', host='', modifier=1, *args, **kwargs):
        self.query = query % options.database
        self.label = label
        self.unit = unit
        self.stdout = stdout
        self.options = options
        self.host = host
        self.modifier = modifier
    
    def run_on_connection(self, connection):
        cur = connection.cursor()
        cur.execute(self.query)
        self.query_result = cur.fetchone()[0]
    
    def finish(self):
        stdout = self.stdout % str(self.result)
        stdout = '%s%s' % (STDOUT_PREFIX[self.code], stdout)
        if not self.options.no_perfdata:
            stdout = "%s|%s" % (stdout, self.perfdata)
        raise NagiosReturn(stdout, self.code)
    
    def calculate_result(self):
        self.result = round(float(self.query_result) * self.modifier, 2)

    def generate_perfdata(self):
        if is_within_range(self.options.critical, self.result):
           self.code = 2
        elif is_within_range(self.options.warning, self.result):
            self.code = 1
        else:
            self.code = 0

        self.perfdata = "'%s'=%s%s;%s;%s;;" % (  self.label,
                                               str(self.result),
                                               self.unit,
                                               self.options.warning or '',
                                               self.options.critical or '')

    def do(self, connection):
        self.run_on_connection(connection)
        self.calculate_result()
        self.generate_perfdata()

class MSSQLDivideQuery(MSSQLQuery):
    
    def calculate_result(self):
        self.result = round((float(self.query_result[0]) / self.query_result[1]) * self.modifier, 2)
    
    def run_on_connection(self, connection):
        cur = connection.cursor()
        cur.execute(self.query)
        self.query_result = [x[0] for x in cur.fetchall()]

class MSSQLDeltaQuery(MSSQLQuery):
    
    def make_pickle_name(self):
        tmpdir = tempfile.gettempdir()
        tmpname = hash(self.host + self.database + self.query)
        self.picklename = '%s/mssql-%s.tmp' % (tmpdir, tmpname)
    
    def calculate_result(self):
        self.make_pickle_name()
        
        try:
            tmpfile = open(self.picklename)
        except IOError:
            tmpfile = open(self.picklename, 'w')
            tmpfile.close()
            tmpfile = open(self.picklename)
        try:
            try:
                last_run = pickle.load(tmpfile)
            except EOFError, ValueError:
                last_run = { 'time' : None, 'value' : None }
        finally:
            tmpfile.close()
        
        if last_run['time']:
            old_time = last_run['time']
            new_time = time.time()
            old_val  = last_run['query_result']
            new_val  = self.query_result
            self.result = round(((new_val - old_val) / (new_time - old_time)) * self.modifier, 2)
        else:
            self.result = None
        
        new_run = { 'time' : time.time(), 'query_result' : self.query_result }
        
        #~ Will throw IOError, leaving it to aquiesce
        tmpfile = open(self.picklename, 'w')
        pickle.dump(new_run, tmpfile)
        tmpfile.close()

def is_within_range(nagstring, value):
    if not nagstring:
        return False
    import re
    import operator
    first_float = r'(?P<first>(-?[0-9]+(\.[0-9]+)?))'
    second_float= r'(?P<second>(-?[0-9]+(\.[0-9]+)?))'
    actions = [ (r'^%s$' % first_float,lambda y: (value > float(y.group('first'))) or (value < 0)),
                (r'^%s:$' % first_float,lambda y: value < float(y.group('first'))),
                (r'^~:%s$' % first_float,lambda y: value > float(y.group('first'))),
                (r'^%s:%s$' % (first_float,second_float), lambda y: (value < float(y.group('first'))) or (value > float(y.group('second')))),
                (r'^@%s:%s$' % (first_float,second_float), lambda y: not((value < float(y.group('first'))) or (value > float(y.group('second')))))]
    for regstr,func in actions:
        res = re.match(regstr,nagstring)
        if res: 
            return func(res)
    raise Exception('Improper warning/critical format.')

def parse_args():
    usage = "usage: %prog -H hostname -U user -P password -D database --mode"
    parser = OptionParser(usage=usage)
    
    required = OptionGroup(parser, "Required Options")
    required.add_option('-H', '--hostname', help='Specify MSSQL Server Address', default=None)
    required.add_option('-U', '--user', help='Specify MSSQL User Name', default=None)
    required.add_option('-P', '--password', help='Specify MSSQL Password', default=None)
    parser.add_option_group(required)
    
    connection = OptionGroup(parser, "Optional Connection Information")
    connection.add_option('-I', '--instance', help='Specify instance', default=None)
    connection.add_option('-p', '--port', help='Specify port.', default=None)
    connection.add_option('-D', '--database', help='Specify the database to check', default=None) 
    connection.add_option('--exclude-databases', help='Any database names matching this regex will be ignored', default=None) 
    connection.add_option('--include-databases', help='Only database names matching this regex will be checked', default=None) 
    connection.add_option('--case-sensitive', action="store_true", help='Make the include/exclude regex case-sensitive', default=False) 
    parser.add_option_group(connection)
    
    nagios = OptionGroup(parser, "Nagios Plugin Information")
    nagios.add_option('-w', '--warning', help='Specify warning range.', default=None)
    nagios.add_option('-c', '--critical', help='Specify critical range.', default=None)
    parser.add_option_group(nagios)

    perfdata = OptionGroup(parser, "Performance Data Options")
    perfdata.add_option('-d', '--datasize-unit', help='Force a unit type for modes that return data size: B, KB, MB, GB, TB', default=None) 
    perfdata.add_option('-n', '--no-perfdata', action="store_true", help='Do not return performance data', default=False) 
    parser.add_option_group(perfdata)
    
    debug = OptionGroup(parser, "Debug Options")
    debug.add_option('-l', '--list-databases', action="store_true", help='List all databases on the server', default=False)
    parser.add_option_group(debug)

    mode = OptionGroup(parser, "Mode Options")
    global MODES
    for k, v in zip(MODES.keys(), MODES.values()):
        mode.add_option('--%s' % k, action="store_true", help=v.get('help'), default=False)
    parser.add_option_group(mode)
    options, _ = parser.parse_args()
    
    if not options.hostname:
        parser.error('Hostname is a required option.')
    if not options.user:
        parser.error('User is a required option.')
    if not options.password:
        parser.error('Password is a required option.')
    if options.instance and options.port:
        parser.error('Cannot specify both instance and port.')
    if options.include_databases and options.exclude_databases:
        parser.error('Cannot both include and exclude databases. Pick only one.')
    if options.datasize_unit and options.datasize_unit.upper() in DATASIZE_UNIT:
        for v in ['datasize', 'logsize']:
            options.datasize_unit = options.datasize_unit.upper() 
            MODES[v]['unit'] = options.datasize_unit
            MODES[v]['modifier'] = DATASIZE_UNIT[options.datasize_unit]
            MODES[v]['stdout'] = MODES[v]['stdout'].rstrip('KB') + options.datasize_unit
    elif options.datasize_unit and not options.datasize_unit in DATASIZE_UNIT:
        parser.error('Invalid datasize unit specified.')
    
    options.mode = None
    for arg in mode.option_list:
        if getattr(options, arg.dest) and options.mode:
            parser.error("Must choose one and only Mode Option.")
        elif getattr(options, arg.dest):
            options.mode = arg.dest
    
    if options.mode == 'test' and not options.database:
        parser.error('When running in test mode you must specify a database.')
    
    return options

def connect_db(options):
    host = options.hostname
    if options.instance:
        host += "\\" + options.instance
    elif options.port:
        host += ":" + options.port
    start = time.time()
    mssql = pymssql.connect(host = host, user = options.user, password = options.password, database=options.database)
    total = time.time() - start
    return mssql, total, host

def main():
    options = parse_args()
    
    mssql, total, host = connect_db(options)
    
    if options.list_databases:
        databases = get_all_databases(mssql) 
        print "\n".join(databases)

    elif options.mode =='test':
        run_tests(mssql, options, host)
        
    elif not options.mode or options.mode == 'time2connect':
        return_nagios(  options,
                        stdout='Time to connect was %ss',
                        label='time',
                        unit='s',
                        result=total )
                        
    else:
        run_mode_check(mssql, options, host)

def run_mode_check(mssql, options, host=''):
    check_all_databases = False
    results = {}

    if not options.database:
        databases = get_all_databases(mssql)
        check_all_databases = True
    else:
        databases = [options.database]

    if check_all_databases and options.exclude_databases:
        databases = filter_database_list(databases, options.exclude_databases, options.case_sensitive, True)
    elif check_all_databases and options.include_databases:
        databases = filter_database_list(databases, options.include_databases, options.case_sensitive, False)

    for database in databases:
        options.database = database
        dbconnection, total, host = connect_db(options)
        mssql_query = execute_query(dbconnection, options, host, check_all_databases)
        results[database] = { 'code' : mssql_query.code, 'perfdata' : mssql_query.perfdata }
        dbconnection.close()

    stdout, code = get_multidb_check_output(results, options)

    raise NagiosReturn(stdout, code)

def filter_database_list(databases, regex_string, case_sensitive, invert):
    import re

    if not case_sensitive:
        regex = re.compile(regex_string, re.IGNORECASE)
    else :
        regex = re.compile(regex_string)

    if invert:
        return [x for x in databases if not regex.match(x)]
    else:
        return [x for x in databases if regex.match(x)]

def get_multidb_check_output(results, options):
    warnings = []
    criticals = []
    perfdata_output = []

    for database in results.keys():
        perfdata_output.append(results[database]['perfdata'])
        if results[database]['code'] == 1:
            warnings.append(database)
        elif results[database]['code'] == 2:
            criticals.append(database)

    stdout = str(len(results)) + " database(s) checked for " + MODES[options.mode]['help'].lower() + "."
    if len(criticals) > 0:
        stdout = stdout + " " + str(len(criticals)) + " in a critical state (" + ", ".join(criticals) + ")." 
    if len(warnings) > 0:
        stdout = stdout + " " + str(len(warnings)) + " in a warning state (" + ", ".join(warnings) + ")."
    if len(perfdata_output) > 0 and not options.no_perfdata:
        stdout = stdout + "|" + " ".join(perfdata_output)

    if len(criticals) >= len(warnings) and len(criticals) > 0:
        code = 2
    elif len(warnings) > len(criticals):
        code = 1
    else:
        code = 0
    stdout = STDOUT_PREFIX[code] + stdout

    return stdout, code

def execute_query(mssql, options, host='', check_all_databases=False):
    sql_query = MODES[options.mode]
    sql_query['options'] = options
    sql_query['host'] = host
    query_type = sql_query.get('type')
    if check_all_databases:
        sql_query['label'] = options.database

    if query_type == 'delta':
        mssql_query = MSSQLDeltaQuery(**sql_query)
    elif query_type == 'divide':
        mssql_query = MSSQLDivideQuery(**sql_query)
    else:
        mssql_query = MSSQLQuery(**sql_query)
    mssql_query.do(mssql)

    if not check_all_databases:
        mssql_query.finish()

    return mssql_query

def get_all_databases(mssql):
    cur = mssql.cursor()
    cur.execute(LISTDB_QUERY)
    return [item[0] for item in cur.fetchall()]

def run_tests(mssql, options, host):
    failed = 0
    total  = 0
    del MODES['time2connect']
    del MODES['test']
    for mode in MODES.keys():
        total += 1
        options.mode = mode
        try:
            execute_query(mssql, options, host)
        except NagiosReturn:
            print "%s passed!" % mode
        except Exception, e:
            failed += 1
            print "%s failed with: %s" % (mode, e)
    print '%d/%d tests failed.' % (failed, total)
    
if __name__ == '__main__':
    try:
        main()
    except pymssql.OperationalError, e:
        print e
        sys.exit(3)
    except IOError, e:
        print e
        sys.exit(3)
    except NagiosReturn, e:
        print e.message
        sys.exit(e.code)
    except Exception, e:
        print type(e)
        print "Caught unexpected error. This could be caused by your sys.dm_os_performance_counters not containing the proper entries for this query, and you may delete this service check."
        sys.exit(3)

