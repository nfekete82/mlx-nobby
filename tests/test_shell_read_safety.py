import unittest

from agent.app import validate_shell_read_command


class ShellReadCurlSafetyTests(unittest.TestCase):

    def assert_allowed(self, command):
        result = validate_shell_read_command(command)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "curl")

    def assert_blocked(self, command):
        with self.assertRaises(ValueError):
            validate_shell_read_command(command)

    def test_allows_basic_http_reads(self):
        allowed = [
            "curl https://example.com",
            "curl http://127.0.0.1:8000/health",
            "curl -I https://example.com",
            "curl --head https://example.com",
            "curl -fsS https://example.com",
            "curl -sS https://example.com",
            "curl -fL https://example.com",
            "curl --silent --show-error https://example.com",
        ]

        for command in allowed:
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_blocks_request_method_overrides(self):
        blocked = [
            "curl -X POST https://example.com",
            "curl -XPOST https://example.com",
            "curl --request POST https://example.com",
            "curl --request=POST https://example.com",
        ]

        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)

    def test_blocks_output_files(self):
        blocked = [
            "curl -o /tmp/output https://example.com",
            "curl -o/tmp/output https://example.com",
            "curl --output /tmp/output https://example.com",
            "curl --output=/tmp/output https://example.com",
            "curl -O https://example.com/file",
            "curl --remote-name https://example.com/file",
        ]

        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)

    def test_blocks_config_files(self):
        blocked = [
            "curl -K config.txt https://example.com",
            "curl -Kconfig.txt https://example.com",
            "curl --config config.txt https://example.com",
            "curl --config=config.txt https://example.com",
        ]

        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)

    def test_blocks_non_http_schemes(self):
        blocked = [
            "curl file:///etc/passwd",
            "curl ftp://example.com/file",
            "curl dict://example.com/test",
        ]

        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)

    def test_blocks_other_unsafe_options(self):
        blocked = [
            "curl -d test https://example.com",
            "curl -dtest https://example.com",
            "curl --data test https://example.com",
            "curl -F file=@x https://example.com",
            "curl -T file https://example.com",
            "curl -u user:pass https://example.com",
            "curl -H 'X-Test: value' https://example.com",
        ]

        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)


if __name__ == "__main__":
    unittest.main()
