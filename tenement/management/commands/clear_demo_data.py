from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q

from tenement.models import Property


class Command(BaseCommand):
    help = 'Delete all properties and non-admin users to reset the demo database safely.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required to confirm destructive deletion.',
        )
        parser.add_argument(
            '--keep-staff',
            action='store_true',
            help='Keep staff accounts in addition to admins.',
        )
        parser.add_argument(
            '--keep-field-staff',
            action='store_true',
            help='Keep field staff accounts in addition to admins.',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.WARNING(
                    'This is destructive. Run with --confirm to delete all properties and all non-admin users.'
                )
            )
            return

        protected_user_types = ['admin']
        if options['keep_staff']:
            protected_user_types.append('staff')
        if options['keep_field_staff']:
            protected_user_types.append('field_staff')

        protected_user_ids = list(
            User.objects.filter(userprofile__user_type__in=protected_user_types)
            .values_list('id', flat=True)
        )

        property_count = Property.objects.count()
        deleted_users = User.objects.exclude(id__in=protected_user_ids).count()

        Property.objects.all().delete()
        User.objects.exclude(id__in=protected_user_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted {property_count} properties and {deleted_users} non-admin users. '
                f'Protected roles: {", ".join(protected_user_types)}.'
            )
        )
