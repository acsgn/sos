# Copyright (C) 2014 Michele Baldessari <michele at acksyn.org>

# This file is part of the sos project: https://github.com/sosreport/sos
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from socket import gethostname
from sos.report.plugins import Plugin, RedHatPlugin, DebianPlugin, PluginOpt


class Pcp(Plugin, RedHatPlugin, DebianPlugin):

    short_desc = 'Performance Co-Pilot data'

    plugin_name = 'pcp'
    profiles = ('system', 'performance')
    packages = ('pcp',)

    pcp_conffile = '/etc/pcp.conf'

    # size-limit of PCP logger and manager data collected by default (MB)
    option_list = [
        PluginOpt('pmmgrlogs', default=100,
                  desc='size limit in MB of pmmgr logs'),
        PluginOpt('pmloggerfiles', default=12,
                  desc='number of pmlogger files to collect')
    ]

    pcp_sysconf_dir = None
    pcp_var_dir = None
    pcp_log_dir = None

    pcp_hostname = ''

    def pcp_parse_conffile(self):
        """ Parse PCP configuration """
        try:
            with open(self.pcp_conffile, "r", encoding='UTF-8') as pcpconf:
                lines = pcpconf.readlines()
        except IOError:
            return False
        env_vars = {}
        for line in lines:
            if line.startswith('#'):
                continue
            try:
                (key, value) = line.strip().split('=')
                env_vars[key] = value
            except (ValueError, KeyError):
                # not a line for a key, value pair. Ignore the line.
                pass

        try:
            self.pcp_sysconf_dir = env_vars['PCP_SYSCONF_DIR']
            self.pcp_var_dir = env_vars['PCP_VAR_DIR']
            self.pcp_log_dir = env_vars['PCP_LOG_DIR']
        except Exception:  # pylint: disable=broad-except
            # Fail if all three env variables are not found
            return False

        return True

    def setup(self):
        sizelimit = (None if self.get_option("all_logs")
                     else self.get_option("pmmgrlogs"))
        countlimit = (None if self.get_option("all_logs")
                      else self.get_option("pmloggerfiles"))

        if not self.pcp_parse_conffile():
            self._log_warn(f"could not parse {self.pcp_conffile}")
            return

        # Add PCP_SYSCONF_DIR (/etc/pcp) and PCP_VAR_DIR (/var/lib/pcp/config)
        # unconditionally. Obviously if someone messes up their /etc/pcp.conf
        # in a ridiculous way (i.e. setting PCP_SYSCONF_DIR to '/') this will
        # break badly.
        var_conf_dir = self.path_join(self.pcp_var_dir, 'config')
        self.add_copy_spec([
            self.pcp_sysconf_dir,
            self.pcp_conffile,
            var_conf_dir
        ])

        # We explicitly avoid /var/lib/pcp/config/{pmchart,pmlogconf,pmieconf,
        # pmlogrewrite} as in 99% of the cases they are just copies from the
        # rpms. It does not make up for a lot of size but it contains many
        # files
        self.add_forbidden_path([
            self.path_join(var_conf_dir, 'pmchart'),
            self.path_join(var_conf_dir, 'pmlogconf'),
            self.path_join(var_conf_dir, 'pmieconf'),
            self.path_join(var_conf_dir, 'pmlogrewrite')
        ])

        # Take PCP_LOG_DIR/pmlogger/`hostname` + PCP_LOG_DIR/pmmgr/`hostname`
        # The *default* directory structure for pmlogger is the following:
        # Dir: PCP_LOG_DIR/pmlogger/HOST/ (we only collect the HOST data
        # itself)
        # - YYYYMMDD.HH.MM.{N,N.index,N.meta} N in [0,1,...]
        # - Latest
        # - pmlogger.{log,log.prior}
        #
        # Can be changed via configuration in PCP_SYSCONF_DIR/pmlogger/control
        # As a default strategy, collect up to 100MB data from each dir.
        # Can be overwritten either via pcp.pcplogsize option or all_logs.
        self.pcp_hostname = gethostname()

        # Make sure we only add the two dirs if hostname is set, otherwise
        # we would collect everything
        if self.pcp_hostname != '':
            # collect pmmgr logs up to 'pmmgrlogs' size limit
            path = self.path_join(self.pcp_log_dir, 'pmmgr',
                                  self.pcp_hostname, '*')
            self.add_copy_spec(path, sizelimit=sizelimit, tailit=False)
            # collect newest pmlogger logs up to 'pmloggerfiles' count
            files_collected = 0
            path = self.path_join(self.pcp_log_dir, 'pmlogger',
                                  self.pcp_hostname, '*')
            pmlogger_ls = self.exec_cmd(f"ls -t1 {path}")
            if pmlogger_ls['status'] == 0:
                for line in pmlogger_ls['output'].splitlines():
                    self.add_copy_spec(line, sizelimit=0)
                    files_collected = files_collected + 1
                    if countlimit and files_collected == countlimit:
                        break

        self.add_copy_spec([
            # Collect PCP_LOG_DIR/pmcd and PCP_LOG_DIR/NOTICES
            self.path_join(self.pcp_log_dir, 'pmcd'),
            self.path_join(self.pcp_log_dir, 'NOTICES*'),
            # Collect PCP_VAR_DIR/pmns
            self.path_join(self.pcp_var_dir, 'pmns'),
            # Also collect any other log and config files
            # (as suggested by fche)
            self.path_join(self.pcp_log_dir, '*/*.log*'),
            self.path_join(self.pcp_log_dir, '*/*/*.log*'),
            self.path_join(self.pcp_log_dir, '*/*/config*')
        ])

        # Collect a summary for the current day
        res = self.collect_cmd_output('pcp')
        if res['status'] == 0:
            for line in res['output'].splitlines():
                if line.startswith(' pmlogger:'):
                    arc = line.split()[-1]
                    self.add_cmd_output(
                        f"pmstat -S 00:00 -T 23:59 -t 5m -x -a {arc}",
                        root_symlink="pmstat"
                    )
                    break

# vim: set et ts=4 sw=4 :
