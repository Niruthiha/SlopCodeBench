"""Container runtime integration, using a fake ``docker`` binary that records its calls."""

import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from appctl_cli import container
from appctl_cli.errors import AppctlError
from appctl_cli.output import Output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")

FAKE_DOCKER = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "$FAKE_DOCKER_LOG"
    case "$*" in
      "compose version") exit 0 ;;
      "inspect --type container -f {{.State.Running}} up") echo true; exit 0 ;;
      "inspect --type container -f {{.State.Running}} down") echo false; exit 0 ;;
      "inspect"*) exit 1 ;;
      "volume inspect "*_existing) exit 0 ;;
      "volume inspect"*) exit 1 ;;
      "info"*) echo "$FAKE_DOCKER_ROOT"; exit 0 ;;
      "network connect net bad"|"network disconnect net bad") exit 1 ;;
      "network inspect missing") exit 1 ;;
    esac
    exit 0
""")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(text))


class FakeDockerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        docker = os.path.join(bin_dir, "docker")
        write(docker, FAKE_DOCKER)
        os.chmod(docker, os.stat(docker).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmp, "docker.log")
        env = {"PATH": bin_dir + os.pathsep + "/bin:/usr/bin", "FAKE_DOCKER_LOG": self.log,
               "FAKE_DOCKER_ROOT": os.path.join(self.tmp, "root")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        container._compose_binary.clear()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.output = Output(stdout=self.stdout, stderr=self.stderr)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [line.rstrip("\n") for line in handle if line.strip() != "compose version"]


class ContainerTest(FakeDockerCase):
    def test_status(self):
        self.assertEqual(container.container_status("up", self.output), "running")
        self.assertEqual(container.container_status("down", self.output), "exited")
        self.assertIsNone(container.container_status("gone", self.output))

    def test_runtime_missing(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            with self.assertRaises(AppctlError) as ctx:
                container.container_status("up")
        self.assertEqual(ctx.exception.message, container.RUNTIME_MISSING)

    def test_boot(self):
        self.assertTrue(container.boot_container("up", output=self.output))
        self.assertTrue(container.boot_container("down", output=self.output))
        self.assertTrue(container.boot_container("gone", "nginx", output=self.output))
        calls = self.calls()
        self.assertNotIn("start up", calls)
        self.assertIn("start down", calls)
        self.assertIn("run -d --name gone nginx", calls)

    def test_start_stop_restart(self):
        container.start_container("c", self.output)
        container.stop_container("c", self.output)
        container.restart_container("c", self.output)
        self.assertEqual(self.calls(), ["start c", "stop c", "restart c"])


class ComposeTest(FakeDockerCase):
    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp, "project")
        write(os.path.join(self.project, "docker-compose.yml"), """\
            services:
              web: {image: nginx}
              db: {image: mariadb}
        """)

    def test_files_and_discovery_order(self):
        custom = os.path.join(self.project, container.CUSTOM_COMPOSE_DIR)
        write(os.path.join(custom, "b.yml"), "services: {b: {}}\n")
        write(os.path.join(custom, "a.yaml"), "services: {a: {}}\n")
        write(os.path.join(custom, "notes.txt"), "services: {x: {}}\n")
        files = container.compose_files(self.project)
        self.assertEqual([os.path.relpath(f, self.project) for f in files],
                         ["docker-compose.yml", "user-docker-compose/a.yaml",
                          "user-docker-compose/b.yml"])
        self.assertEqual(container.project_services(self.project), ["web", "db", "a", "b"])

    def test_custom_compose(self):
        override = os.path.join(self.tmp, "custom.yml")
        write(override, "services: {cache: {image: redis}, web: {ports: ['80:80']}}\n")
        files = container.compose_files(self.project, override)
        self.assertEqual(files[-1], override)
        merged = container.load_compose_config(files)
        self.assertEqual(list(merged["services"]), ["web", "db", "cache"])
        self.assertEqual(merged["services"]["web"], {"image": "nginx", "ports": ["80:80"]})

    def test_missing_custom_compose_warns(self):
        files = container.compose_files(self.project, "/nope.yml", self.output)
        self.assertEqual(len(files), 1)
        self.assertEqual(self.stderr.getvalue(), "Warning: File: /nope.yml does not exist. "
                                                 "Falling back to default compose file.\n")

    def test_service_exists(self):
        self.assertTrue(container.service_exists("web", self.project))
        self.assertFalse(container.service_exists("nope", self.project))
        self.assertFalse(container.service_exists("web", os.path.join(self.tmp, "missing")))

    def test_up_down(self):
        base = os.path.join(self.project, "docker-compose.yml")
        container.compose_up(self.project, output=self.output)
        container.compose_up(self.project, ["web"], output=self.output)
        container.compose_down(self.project, output=self.output)
        self.assertEqual(self.calls(), [
            f"compose -f {base} up -d",
            f"compose -f {base} up -d web",
            f"compose -f {base} down --volumes --remove-orphans",
        ])

    def test_exec_tty(self):
        argv = container.compose_exec_command(self.project, "web", "ls -la",
                                              {"skip-tty": True}, user="www")
        self.assertEqual(argv[-8:], ["exec", "-T", "--user", "www", "web", "sh", "-c", "ls -la"])
        argv = container.compose_exec_command(self.project, "web", "ls -la", {"skip-tty": "false"},
                                              shell_wrapper=False)
        self.assertNotIn("-T", argv)
        self.assertEqual(argv[-3:], ["web", "ls", "-la"])


class VolumeNetworkTest(FakeDockerCase):
    def volumes(self):
        return [
            {"name": "existing", "path_to_symlink": os.path.join(self.tmp, "l", "e"),
             "container_path": "/e"},
            {"name": "skipped", "path_to_symlink": os.path.join(self.tmp, "l", "s"),
             "container_path": "/s", "skip_volume": True},
            {"name": "data", "path_to_symlink": os.path.join(self.tmp, "l", "d"),
             "container_path": "/d", "skip_darwin": True},
        ]

    def test_prefix(self):
        self.assertEqual(container.project_prefix("Example.Test"), "exampletest")
        self.assertEqual(container.project_prefix("Example.Test"),
                         container.project_prefix("Example.Test"))

    def test_create_volumes_linux(self):
        created = container.create_volumes("p", self.volumes(), self.output, "Linux")
        self.assertEqual(created, ["p_data"])
        self.assertIn(f"volume create --label {container.VENDOR_LABEL} "
                      f"--label {container.PROJECT_LABEL_KEY}=p p_data", self.calls())
        link = os.path.join(self.tmp, "l", "d")
        self.assertEqual(os.readlink(link), os.path.join(self.tmp, "root", "volumes", "p_data", "_data"))

    def test_create_volumes_darwin(self):
        container.create_volumes("p", self.volumes(), self.output, "Darwin")
        self.assertFalse(os.path.lexists(os.path.join(self.tmp, "l", "d")))

    def test_mounts(self):
        self.assertEqual(container.mounting_volume_array(self.volumes(), "Linux"),
                         ["existing:/e", "skipped:/s", "data:/d"])
        self.assertEqual(container.mounting_volume_array(self.volumes(), "Darwin"),
                         [os.path.join(self.tmp, "l", "e") + ":/e",
                          os.path.join(self.tmp, "l", "s") + ":/s"])

    def test_networks(self):
        self.assertTrue(container.create_network("net", self.output, "p"))
        self.assertIn(f"network create --label {container.VENDOR_LABEL} "
                      f"--label {container.PROJECT_LABEL_KEY}=p net", self.calls())
        container.connect_network("net", "good", self.output)
        self.assertIn("Success: Project connected to good.", self.stdout.getvalue())
        with self.assertRaises(AppctlError) as ctx:
            container.connect_network("net", "bad", self.output)
        self.assertEqual(ctx.exception.message, "There was some error connecting to bad.")
        self.assertTrue(container.disconnect_network("net", "good", self.output))
        self.assertFalse(container.disconnect_network("net", "bad", self.output))
        self.assertIn("Warning: Error in disconnecting from Docker network of bad",
                      self.stderr.getvalue())
        self.assertTrue(container.remove_network("net", self.output))
        self.assertTrue(container.network_exists("net", self.output))
        self.assertFalse(container.network_exists("missing", self.output))


class SiteConfigCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        write(os.path.join(self.tmp, "docker-compose.yml"), """\
            services:
              zeta: {image: a}
              alpha: {image: b}
              mid: {image: c}
        """)
        write(os.path.join(self.tmp, "home", "config.yml"), "")

    def run_cli(self, *args, config=""):
        config_path = os.path.join(self.tmp, "home", "config.yml")
        write(config_path, config)
        env = dict(os.environ, APPCTL_CONFIG_PATH=config_path,
                   APPCTL_ROOT_DIR=os.path.join(self.tmp, "home"))
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=env, cwd=self.tmp)

    def test_services_in_file_order(self):
        result = self.run_cli("site", "config", "--services")
        self.assertEqual((result.returncode, result.stdout), (0, "zeta\nalpha\nmid\n"))

    def test_custom_compose(self):
        write(os.path.join(self.tmp, "extra.yml"), "services: {beta: {}, alpha: {}}\n")
        result = self.run_cli("site", "config", "--services", config="custom-compose: extra.yml\n")
        self.assertEqual(result.stdout, "zeta\nalpha\nmid\nbeta\n")

    def test_missing_custom_compose(self):
        result = self.run_cli("site", "config", "--services", config="custom-compose: nope.yml\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "zeta\nalpha\nmid\n")
        self.assertEqual(result.stderr, "Warning: File: nope.yml does not exist. "
                                        "Falling back to default compose file.\n")


if __name__ == "__main__":
    unittest.main()
