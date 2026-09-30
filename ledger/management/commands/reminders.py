import time

from django.core.management.base import BaseCommand

from ledger.reminders import run_once


class Command(BaseCommand):
    help = "Send due push reminders (daily log, bills, card statements). --loop checks every minute."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")

    def handle(self, *args, loop=False, **opts):
        while True:
            for key in run_once():
                self.stdout.write(f"sent {key}")
            if not loop:
                return
            time.sleep(60 - time.time() % 60)  # wake at the top of each minute
