import unittest
from unittest.mock import patch
from deployment.install_influ_access import normalise_emails, configure_and_acceptance


class EmailAccessInstallerTests(unittest.TestCase):
    def test_exact_two_normalised_emails_required(self):
        self.assertEqual(normalise_emails([' Owner@Example.invalid ', 'CREATOR@example.invalid']),
                         ['owner@example.invalid', 'creator@example.invalid'])
        for values in ([], ['a@example.invalid'], ['a@example.invalid', 'A@example.invalid'],
                       ['a@example.invalid', 'b@example.invalid', 'c@example.invalid'], ['invalid', 'b@example.invalid']):
            with self.subTest(values=values), self.assertRaises(ValueError):
                normalise_emails(values)

    @patch('deployment.install_influ_access.installer.django')
    def test_emails_are_data_in_server_django_process_not_executable_source(self, django):
        configure_and_acceptance(None, ["a'@example.invalid", 'b@example.invalid'])
        command = django.call_args.args[0]
        self.assertEqual(command[:2], ['shell', '-c'])
        compile(command[2], '<acceptance>', 'exec')
        self.assertIn('coupon.save(update_fields=', command[2])
        self.assertNotIn('create_user(', command[2])
