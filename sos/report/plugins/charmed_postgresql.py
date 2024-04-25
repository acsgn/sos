# This file is part of the sos project: https://github.com/sosreport/sos
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from typing import Optional
import yaml

from sos.report.plugins import Plugin, UbuntuPlugin

SNAP_COMMON_PATH = "/var/snap/charmed-postgresql/common"
SNAP_CURRENT_PATH = "/var/snap/charmed-postgresql/current"

PATHS = {
    "POSTGRESQL_CONF": SNAP_COMMON_PATH + "/var/lib/postgresql",
    "POSTGRESQL_LOGS": SNAP_COMMON_PATH + "/var/log/postgresql",
    "PATRONI_CONF": SNAP_CURRENT_PATH + "/etc/patroni",
    "PATRONI_LOGS": SNAP_COMMON_PATH + "/var/log/patroni",
    "PGBACKREST_CONF": SNAP_CURRENT_PATH + "/etc/pgbackrest",
    "PGBACKREST_LOGS": SNAP_COMMON_PATH + "/var/log/pgbackrest",
    "PGBOUNCER_CONF": SNAP_CURRENT_PATH + "/etc/pgbouncer",
    "PGBOUNCER_LOGS": SNAP_COMMON_PATH + "/var/log/pgbouncer",
}

RUN_AS_SNAP_DAEMON = "runuser -u snap_daemon --"
PSQL = "charmed-postgresql.psql"
PATRONICTL = "charmed-postgresql.patronictl"


class CharmedPostgreSQL(Plugin, UbuntuPlugin):

    short_desc = "Charmed PostgreSQL"
    plugin_name = "charmed_postgresql"
    packages = ('charmed-postgresql',)

    @property
    def patroni_cluster_name(self) -> Optional[str]:
        with open(f"{PATHS['PATRONI_CONF']}/patroni.yaml") as file:
            patroni_config = yaml.safe_load(file)

        if patroni_config:
            return patroni_config.get("scope")

    @property
    def patronictl_args(self) -> str:
        return f"--config-file {PATHS['PATRONI_CONF']}/patroni.yaml"

    @property
    def postgresql_host(self) -> Optional[str]:
        with open(f"{PATHS['PATRONI_CONF']}/patroni.yaml") as file:
            patroni_config = yaml.safe_load(file)

        if patroni_config:
            postgresql = patroni_config.get("postgresql", {})
            address = postgresql.get("connect_address")
            if address:
                return address.split(":")[0]

    @property
    def postgresql_port(self) -> Optional[str]:
        with open(f"{PATHS['PATRONI_CONF']}/patroni.yaml") as file:
            patroni_config = yaml.safe_load(file)

        if patroni_config:
            postgresql = patroni_config.get("postgresql", {})
            address = postgresql.get("connect_address")
            if address:
                return address.split(":")[1]

    @property
    def postgresql_username(self) -> Optional[str]:
        with open(f"{PATHS['PATRONI_CONF']}/patroni.yaml") as file:
            patroni_config = yaml.safe_load(file)

        if patroni_config:
            postgresql = patroni_config.get("postgresql", {})
            authentication = postgresql.get("authentication", {})
            superuser = authentication.get("superuser", {})
            return superuser.get("username")

    @property
    def postgresql_password(self) -> Optional[str]:
        with open(f"{PATHS['PATRONI_CONF']}/patroni.yaml") as file:
            patroni_config = yaml.safe_load(file)

        if patroni_config:
            postgresql = patroni_config.get("postgresql", {})
            authentication = postgresql.get("authentication", {})
            superuser = authentication.get("superuser", {})
            return superuser.get("password")

    @property
    def psql_args(self) -> str:
        return (f"-U {self.postgresql_username} "
                f"-h {self.postgresql_host} "
                f"-p {self.postgresql_port} "
                r"-d postgres -P pager=off")

    def setup(self):
        # --- FILE EXCLUSIONS ---

        # Keys and certificates
        self.add_forbidden_path([
            f"{PATHS['PATRONI_CONF']}/*.pem",
            f"{PATHS['PGBOUNCER_CONF']}/*.pem",
        ])

        # --- FILE INCLUSIONS ---

        self.add_copy_spec([
            f"{PATHS['POSTGRESQL_CONF']}/*.conf*",
            f"{PATHS['POSTGRESQL_LOGS']}",
            f"{PATHS['PATRONI_CONF']}/*.y*ml",
            f"{PATHS['PATRONI_LOGS']}",
            f"{PATHS['PGBACKREST_CONF']}",
            f"{PATHS['PGBACKREST_LOGS']}",
            f"{PATHS['PGBOUNCER_CONF']}",
            f"{PATHS['PGBOUNCER_LOGS']}",
        ])

        # --- SNAP LOGS ---

        self.add_journal("snap.charmed-postgresql.*")

        # --- SNAP INFO ---

        self.add_cmd_output(
            "snap info charmed-postgresql",
            suggest_filename="snap-info",
        )

        # --- TOPOLOGY ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PATRONICTL} {self.patronictl_args} "
             f"topology {self.patroni_cluster_name}"),
            suggest_filename="patroni-topology",
        )

        # --- HISTORY ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PATRONICTL} {self.patronictl_args} "
             f"history {self.patroni_cluster_name}"),
            suggest_filename="patroni-history",
        )

        # --- DCS CONFIGS ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PATRONICTL} {self.patronictl_args} "
             f"show-config {self.patroni_cluster_name}"),
            suggest_filename="patroni-dcs-config",
        )

        # --- DATABASES ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PSQL} {self.psql_args} "
             r"-c '\l+'"),
            suggest_filename="postgresql-databases",
            env={"PGPASSWORD": self.postgresql_password},
        )

        # --- USERS ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PSQL} {self.psql_args} "
             r"-c '\duS+'"),
            suggest_filename="postgresql-users",
            env={"PGPASSWORD": self.postgresql_password},
        )

        # --- TABLES ---

        self.add_cmd_output(
            (f"{RUN_AS_SNAP_DAEMON} "
             f"{PSQL} {self.psql_args} "
             r"-c '\dtS+'"),
            suggest_filename="postgresql-tables",
            env={"PGPASSWORD": self.postgresql_password},
        )

    def postproc(self):
        # --- SCRUB PASSWORDS ---

        # Match lines containing password: and
        # followed by anything which may be enclosed with "
        self.do_path_regex_sub(
            f"{PATHS['PATRONI_CONF']}/*",
            r'(password: )"?.*"?',
            r'\1"*********"',
        )

        # https://pgbackrest.org/configuration.html#section-repository/option-repo-s3-key
        # https://pgbackrest.org/configuration.html#section-repository/option-repo-s3-key-secret
        self.do_path_regex_sub(
            f"{PATHS['PGBACKREST_CONF']}/pgbackrest.conf",
            r'(.*s3-key.*=).*',
            r'\1*********',
        )

        # https://www.pgbouncer.org/config.html#authentication-file-format
        self.do_path_regex_sub(
            f"{PATHS['PGBOUNCER_CONF']}/pgbouncer/userlist.txt",
            r'(".*" )".*"',
            r'\1"*********"',
        )
