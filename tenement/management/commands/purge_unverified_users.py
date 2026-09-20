"""
Management command: purge_unverified_users
==========================================
Deletes user accounts whose email has never been verified and whose
registration is older than a configurable threshold (default: 24 hours).

Usage
-----
    python manage.py purge_unverified_users
    python manage.py purge_unverified_users --hours 48
    python manage.py purge_unverified_users --dry-run

Scheduling (Linux cron)
-----------------------
Add to your server crontab with:

    crontab -e

Then add one of these lines:

    # Run every 6 hours
    0 */6 * * * /path/to/venv/bin/python /path/to/project/manage.py purge_unverified_users >> /var/log/bwari_purge.log 2>&1

    # Run once a day at midnight
    0 0 * * * /path/to/venv/bin/python /path/to/project/manage.py purge_unverified_users >> /var/log/bwari_purge.log 2>&1

Replace /path/to/venv and /path/to/project with your actual paths.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Delete unverified user accounts older than N hours (default: 4).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Delete unverified accounts older than this many hours (default: 4).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be deleted without actually deleting anything.',
        )

    def handle(self, *args, **options):
        hours    = options['hours']
        dry_run  = options['dry_run']
        cutoff   = timezone.now() - timedelta(hours=hours)

        qs = User.objects.filter(
            userprofile__email_verified=False,
            date_joined__lt=cutoff,
        )

        count = qs.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No stale unverified accounts found.'))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would delete {count} unverified account(s) '
                    f'older than {hours} hour(s):'
                )
            )
            for user in qs.order_by('date_joined')[:50]:   # preview up to 50
                self.stdout.write(f'  • {user.username} ({user.email}) — joined {user.date_joined:%Y-%m-%d %H:%M UTC}')
            if count > 50:
                self.stdout.write(f'  … and {count - 50} more.')
            return

        # Collect info before deletion for the log
        sample = list(qs.order_by('date_joined').values_list('username', 'email')[:10])
        deleted_count, _ = qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f'Purged {deleted_count} unverified account(s) '
                f'older than {hours} hour(s).'
            )
        )
        for username, email in sample:
            self.stdout.write(f'  ✓ {username} ({email})')
        if deleted_count > 10:
            self.stdout.write(f'  … and {deleted_count - 10} more.')