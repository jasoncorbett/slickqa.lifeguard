#!/usr/bin/env python
__author__ = 'jcorbett'

# Lifeguard watches over a pool of machines.  Eventually this will be an add-on library to slick, but that would take
# a little longer to do, so this command line version is implemented in the mean time.

import os
import sys
import argparse
import httplib2
import urllib
import json
import types
import time

cmdline_parser = argparse.ArgumentParser()
commands = cmdline_parser.add_subparsers(title='Available Commands')

class SlickError(Exception):
    pass

json_content = {'Content-Type': 'application/json'}

class SlickAsPy(object):

    def __init__(self, baseurl, username='tcrunij', password='f00b@r'):
        self.baseurl = baseurl
        self.http_connection = httplib2.Http()
        self.http_connection.add_credentials(username, password)

    def _get_url(self, *args, **kwargs):
        if len(kwargs) > 0:
            return '/'.join([self.baseurl,] + list(args)) + "?" + urllib.urlencode(kwargs)
        else:
            return '/'.join([self.baseurl,] + list(args))

    def _safe_return(self, response, content):
        if response['status'] == "200":
            return json.loads(content)
        else:
            raise SlickError("Response: {}\nContent:{}".format(response, content))

    def _safe_get(self, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs))
        return self._safe_return(response, content)

    def _safe_post(self, post_data, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs), 'POST', json.dumps(post_data), json_content)
        return self._safe_return(response, content)

    def get_host_status(self, name):
        return self._safe_get("hoststatus", name)

    def cancel_result(self, result, reason="This test has been canceled because it was taking too long to finish."):
        resultid = 0
        if isinstance(result, types.StringTypes):
            resultid = result
        elif isinstance(result, types.DictionaryType):
            resultid = result['id']
        else:
            raise SlickError("Invalid type passed to cancel_result's result parameter: {}".format(type(result)))
        return self._safe_post(reason, "results", resultid, "cancel")

class MicroManagerError(Exception):
    pass

class MicroManager(object):

    def __init__(self, hostname, username='growqa', password='f00b@r'):
        self.hostname = hostname
        self.baseurl = 'http://' + hostname + ":4321/api"
        self.http_connection = httplib2.Http()
        self.http_connection.add_credentials(username, password)

    def _get_url(self, *args, **kwargs):
        if len(kwargs) > 0:
            return '/'.join([self.baseurl,] + list(args)) + "?" + urllib.urlencode(kwargs)
        else:
            return '/'.join([self.baseurl,] + list(args))

    def _safe_return(self, response, content):
        if response['status'] == "200":
            return json.loads(content)
        else:
            raise MicroManagerError("Error from Remote Machine '{}':\nResponse: {}\nContent:{}".format(self.hostname, response, content))

    def _safe_get(self, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs))
        return self._safe_return(response, content)

    def _safe_post(self, post_data, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs), 'POST', json.dumps(post_data), json_content)
        return self._safe_return(response, content)

    def _safe_put(self, post_data, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs), 'PUT', json.dumps(post_data), json_content)
        return self._safe_return(response, content)

    def _safe_delete(self, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs), 'DELETE')
        return self._safe_return(response, content)

    def _safe_delete_with_data(self, data, *args, **kwargs):
        response, content = self.http_connection.request(self._get_url(*args, **kwargs), 'DELETE', json.dumps(data), json_content)
        return self._safe_return(response, content)

    def find_processes_by_name(self, process_name):
        return self._safe_get("processes", name=process_name)

    def kill_process(self, pid, nice=True):
        if nice:
            return self._safe_delete("processes", str(pid))
        else:
            return self._safe_delete("processes", str(pid), force=True)

    def delete_path(self, path):
        return self._safe_delete_with_data({'Path': path}, "files")

    def get_file_contents(self, path):
        mmpath = self._safe_put({'Path': path}, "files", "content")
        if mmpath['Exists']:
            mmpath['Content'] = bytearray(mmpath['Content'])
        return mmpath

    def upload_file(self, local, remote):
        if local is None or local == "":
            return None
        if not os.path.exists(local):
            return None
        content = []
        with open(local, 'r') as local_file:
            content = list(bytearray(local_file.read()))
        mmpath = self._safe_post({'Path': remote, 'Content': content}, 'files', 'content')
        if mmpath['Exists']:
            mmpath['Content'] = bytearray(mmpath['Content'])
        return mmpath

    def get_env(self):
        retval = {}
        for entry in self._safe_get("env"):
            retval[entry['Key']] = entry['Value']
        return retval

    def mkdir(self, path):
        return self._safe_post({'Path': path}, 'files', 'mkdir')

    def get_disks(self):
        return self._safe_get('disks')


    def run_process(self, proc_start_obj):
        return self._safe_post(proc_start_obj, "processes")

    def kill_all(self, procname):
        """
        Kill all the processes with name procname.  This will retry a force kill only 3 times, then raise an error.
        """
        procs = self.find_processes_by_name(procname)
        for proc in procs:
            result = self.kill_process(proc['PID'])
            if not result['HasExited']:
                for i in xrange(3):
                    result = self.kill_process(result['PID'], False)
                    if result['HasExited']:
                        break
                else:
                    raise MicroManagerError("Process with name'{}' and PID '{}' would not exit on machine '{}'.".format(procname, proc['PID'], self.hostname))

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, create_engine
from sqlalchemy.orm import relationship, backref, sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()
engine = create_engine('sqlite:///' + os.path.expanduser('~/.pool.db'))
Session = sessionmaker(bind=engine)

class Environment(Base):
    """
    This holds information on a build server and a slick instance that the machine should point to.
    """
    __tablename__ = 'environments'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    slickurl = Column(String)
    buildurl = Column(String)
    filename = Column(String)
    tcrunijsubdir = Column(String)

    def __repr__(self):
        return "Environment(id=%d, name='%s', slickurl='%s')" % (self.id, self.name, self.slickurl)

class Alert(Base):
    """
    Alerts are issues for a machine that need to be resolved.  Sometimes they can be auto-resolved, some require
    intervention.
    """
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True)
    issued = Column(DateTime, nullable=False)
    alert_type = Column(String, nullable=False)
    resolved =  Column(DateTime, nullable=True)
    resolution = Column(String)
    machine_id = Column(Integer, ForeignKey('machines.id'))
    machine = relationship('PoolMachine', backref=backref('alerts', order_by=issued))


class PoolMachine(Base):
    """
    Data Structure that holds information about a machine in the pool.
    """
    __tablename__ = 'machines'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    hostname = Column(String)
    online = Column(Boolean)
    environment_id = Column(Integer, ForeignKey('environments.id'))
    environment = relationship('Environment', backref=backref('machines', order_by=id))

    def __repr__(self):
        return "PoolMachine(id=%d, name='%s', hostname='%s', environment=%s)" % (self.id, self.name, self.hostname, repr(self.environment))

    @staticmethod
    def summary_header():
        return 'Name'.ljust(20) + 'Hostname'.ljust(40) + "Status".ljust(10) + 'Env Name'

    def summary(self):
        online = "Offline"
        if self.online:
            online =  "Online"
        return self.name.ljust(20) + self.hostname.ljust(40) + online.ljust(10) + self.environment.name

    def check_slick_status(self):
        """
        Check slick to see if the machine has checked in within the last 5 minutes, or a test is running and hasn't
        been running longer than 15 minutes.
        """
        retval = []
        slick = SlickAsPy(self.environment.slickurl + "/api")
        status = slick.get_host_status(self.name)
        if status['currentWork'] is None:
            seconds_since_last_checkin = (int(time.time() * 1000) - status['lastCheckin'])
            if seconds_since_last_checkin < 300000:
                retval.append(CheckStatus(CheckStatus.CHECK_SLICK_CHECKIN, CheckStatus.STATUS_PASS))
            else:
                retval.append(CheckStatus(CheckStatus.CHECK_SLICK_CHECKIN, CheckStatus.STATUS_FAIL, "It's been {} minutes since the last checkin.".format(seconds_since_last_checkin / 60000)))
            retval.append(CheckStatus(CheckStatus.CHECK_TEST_RUNTIME, CheckStatus.STATUS_NA))
        else:
            retval.append(CheckStatus(CheckStatus.CHECK_SLICK_CHECKIN, CheckStatus.STATUS_NA))
            seconds_since_test_started = (int(time.time() * 1000) - status['currentWork']['recorded'])
            if seconds_since_test_started < 900000:
                retval.append(CheckStatus(CheckStatus.CHECK_SLICK_CHECKIN, CheckStatus.STATUS_PASS))
            else:
                retval.append(CheckStatus(CheckStatus.CHECK_SLICK_CHECKIN, CheckStatus.STATUS_FAIL, "It's been {} minutes since the current test started.".format(seconds_since_test_started / 60000)))
        return retval

    def check_java_processes(self):
        """
        Check the number of Java processes on the system, there should be between 1 and 2 processes, no more, no less.
        """
        mm = MicroManager(self.hostname)
        java_processes = mm.find_processes_by_name("java")
        if len(java_processes) > 2 or len(java_processes) == 0:
            return [CheckStatus(CheckStatus.CHECK_JAVA_PROCESS_COUNT, CheckStatus.STATUS_FAIL, "There are {} java processes running".format(len(java_processes))), ]
        else:
            return [CheckStatus(CheckStatus.CHECK_JAVA_PROCESS_COUNT, CheckStatus.STATUS_PASS), ]

    def check_firefox_processes(self):
        """
        Check the number of firefox processes on the system, there should be no more than 2 processes
        """
        mm = MicroManager(self.hostname)
        ff_procs = mm.find_processes_by_name("firefox")
        if len(ff_procs) > 2:
            return [CheckStatus(CheckStatus.CHECK_FIREFOX_PROCESS_COUNT, CheckStatus.STATUS_FAIL, "There are {} firefox processes running".format(len(ff_procs))), ]
        else:
            return [CheckStatus(CheckStatus.CHECK_FIREFOX_PROCESS_COUNT, CheckStatus.STATUS_PASS), ]

    def perform_checks(self):
        """
        Perform all the checks, and return a list of CheckStatus objects.
        """
        retval = []
        retval.extend(self.check_slick_status())
        retval.extend(self.check_java_processes())
        retval.extend(self.check_firefox_processes())
        return retval

    def stop_agent(self):
        mm = MicroManager(self.hostname)
        mm.kill_all("java")
        mm.kill_all("firefox")

    def start_agent(self):
        mm = MicroManager(self.hostname)
        agent_proc = {
            "UseShellExecute": True,
            "FileName": "java",
            "Arguments": "-jar automation-agent-1.0-SNAPSHOT.jar",
            "WorkingDirectory": "C:\\\\Users\\growqa\\Desktop\\automation"
        }
        mm.run_process(agent_proc)


    def reset_agent(self):
        self.stop_agent()
        mm = MicroManager(self.hostname)
        for path in ["C:\\\\Users\\growqa\\AppData\\Local\\Temp", "C:\\\\Users\\growqa\\Desktop\\automation\\tcrunij", "C:\\\\Users\\growqa\\Desktop\\automation\\hs-tcrunij", "C:\\\\Users\\growqa\\Desktop\\automation\\tcrunij.tar.gz", "C:\\\\Users\\growqa\\Desktop\\automation\\hs-tcrunij.tar.gz", "C:\\\\Users\\growqa\\Desktop\\automation\\current.build"]:
            try:
                mm.delete_path(path)
            except MicroManagerError:
                pass
        self.start_agent()



class CheckStatus:

    STATUS_FAIL="FAIL"
    STATUS_PASS="PASS"
    STATUS_NA="N/A"

    CHECK_SLICK_CHECKIN='slick check-in time within 5 minutes'
    CHECK_TEST_RUNTIME='runtime of test less than 15 minutes'
    CHECK_JAVA_PROCESS_COUNT='1 or 2 java processes running'
    CHECK_FIREFOX_PROCESS_COUNT='<2 firefox processes running'

    def __init__(self, check, status, detail=""):
        self.check = check
        self.status = status
        self.detail = detail

    @staticmethod
    def summary_header():
        return "Check".ljust(40) + "Status   Detail"

    def summary(self):
        return self.check.ljust(40) + self.status.ljust(9) + self.detail

class MachineFinder:
    """
    A class responsible for finding machines via different command line options.
    """

    def __init__(self, finder):
        self.finder = finder

    def find_machines(self, session):
        if self.finder == 'all':
            return session.query(PoolMachine).order_by(PoolMachine.id).all()
        if self.finder.startswith('env:'):
            envname = self.finder[4:]
            return session.query(PoolMachine).join(Environment).filter(Environment.name==envname).order_by(PoolMachine.id).all()
        if self.finder.startswith('state:'):
            state = self.finder[6:]
            boolstate = False
            if state.lower() == 'online':
                boolstate = True
            elif not state.lower() == 'offline':
                print "ERROR: Invalid state %s" % state
                sys.exit(1)
            return session.query(PoolMachine).filter(PoolMachine.online == boolstate).order_by(PoolMachine.id).all()
        if self.finder.startswith('hostname:'):
            hostname = self.finder[len('hostname:'):]
            return session.query(PoolMachine).filter(PoolMachine.hostname.like('%' + hostname + '%')).order_by(PoolMachine.id).all()
        return session.query(PoolMachine).filter(PoolMachine.name.like('%' + self.finder + '%')).order_by(PoolMachine.id).all()

    @staticmethod
    def epilog_text():
        retval = "Valid Finders:\n"
        retval += "\t[name or partial name]                  The name of the machine or part of the name.\n"
        retval += "\tenv:[environment name]                  Find machines by what environment they are in\n"
        retval += "\tstate:[offline or online]               List any machines in offline or online mode\n"
        retval += "\thostname:[all or part of the hostname]  All or part of the hostname\n"
        retval += "\tall                                     All machines\n"
        return retval



def init_new_db(args):
    """
    Create a new database on a machine.  By consequence, if one already exists this method will wipe it out.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = Session()
    session.add(Environment(name='normal', slickurl='http://slicker.homestead-corp.com/slickij', buildurl='?', filename='hs-tcrunij.tar.gz', tcrunijsubdir='hs-tcrunij/tcrunij'))
    session.add(Environment(name='dev', slickurl='http://octomom.homestead-corp.com/slickij', buildurl='?', filename='tcrunij.tar.gz', tcrunijsubdir='tcrunij/tcrunij'))
    session.commit()
init_parser = commands.add_parser('init', help="initialize the pool database")
init_parser.set_defaults(func=init_new_db)


def add_machine(args):
    """
    Add a machine to the pool.
    """
    session = Session()
    # the following is used to help with code completion
    env = Environment(name=args.environment)
    try:
        env = session.query(Environment).filter_by(name=args.environment).one()
    except NoResultFound:
        print "ERROR: couldn't find environment %s" % args.environment
        sys.exit(1)
    machine = PoolMachine(name=args.name, hostname=args.hostname, environment=env, online=True)
    session.add(machine)
    session.commit()
    print repr(machine)
add_machine_parser = commands.add_parser('addmachine', help='Add a machine to the pool database')
add_machine_parser.add_argument('name', help='the name that this machine is known by in slick')
add_machine_parser.add_argument('hostname', help='the hostname or ip address of the machine')
add_machine_parser.add_argument('environment', help='the slick environment this machine reports to')
add_machine_parser.set_defaults(func=add_machine)


def list_machines(args):
    """
    Print a list of matching machines.
    """
    session = Session()
    finder = MachineFinder(args.finder)
    machines = finder.find_machines(session)
    print "Machines Found: %d" % (len(machines))
    if len(machines) > 0:
        print
        print PoolMachine.summary_header()
        print "-" * 80
        for machine in machines:
            print machine.summary()
list_machines_parser = commands.add_parser('list', help='List matching machines', epilog=MachineFinder.epilog_text(), formatter_class=argparse.RawDescriptionHelpFormatter)
list_machines_parser.add_argument('finder', help='A valid machine finder')
list_machines_parser.set_defaults(func=list_machines)

def check_machines(args):
    """
    Check all the machines found via the finder argument, and print the check status results
    """
    session = Session()
    finder = MachineFinder(args.finder)
    machines = finder.find_machines(session)
    print "Machines Found: %d" % (len(machines))
    if len(machines) > 0:
        print
        print CheckStatus.summary_header()
        print "=" * 80
        for machine in machines:
            print machine.hostname + ":"
            print '-' * (len(machine.hostname) + 1)
            check_statuses = machine.perform_checks()
            for check_status in check_statuses:
                print check_status.summary()
check_machines_parser = commands.add_parser('check', help='Perform diagnostic checks on found machines', epilog=MachineFinder.epilog_text(), formatter_class=argparse.RawDescriptionHelpFormatter)
check_machines_parser.add_argument('finder', help='A valid machine finder (you can test it with the list command)')
check_machines_parser.set_defaults(func=check_machines)

def reset_machines(args):
    """
    Run the agent reset on all the found machines.
    """
    session = Session()
    finder = MachineFinder(args.finder)
    machines = finder.find_machines(session)
    print "Machines Found: %d" % (len(machines))
    if len(machines) > 0:
        print
        print "Resetting Agent on machines:"
        for machine in machines:
            sys.stdout.write(machine.hostname + "...")
            sys.stdout.flush()
            machine.reset_agent()
            print "Done"
reset_machines_parser = commands.add_parser('reset', help='Stop, remove files, then start the agent on all found machines', epilog=MachineFinder.epilog_text(), formatter_class=argparse.RawDescriptionHelpFormatter)
reset_machines_parser.add_argument('finder', help='A valid machine finder (you can test it with the list command)')
reset_machines_parser.set_defaults(func=reset_machines)




if __name__ == '__main__':
    args = cmdline_parser.parse_args()
    args.func(args)