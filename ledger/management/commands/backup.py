from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger import backup


class Command(BaseCommand):
    help = "Write a full JSON backup to DATA_DIR/backups/ and keep the newest --keep files (default 14)."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14)

    def handle(self, *args, keep=14, **opts):
        import json

        folder = settings.DATA_DIR / "backups"
        folder.mkdir(exist_ok=True)
        path = folder / f"paisapeek-{timezone.localtime():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(backup.export(), ensure_ascii=False))
        # Rotate only our scheduled files; "before-restore-*" safety copies are left alone.
        for old in sorted(folder.glob("paisapeek-*.json"))[:-keep] if keep > 0 else []:
            old.unlink()
        self.stdout.write(str(path))
