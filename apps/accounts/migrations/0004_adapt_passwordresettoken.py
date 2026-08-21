from django.db import migrations, models
import uuid

import apps.accounts.models.password_reset_token


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_passwordresettoken"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="passwordresettoken",
            name="used_at",
        ),
        migrations.AddField(
            model_name="passwordresettoken",
            name="is_used",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="passwordresettoken",
            name="token",
            field=models.CharField(
                db_index=True,
                default=apps.accounts.models.password_reset_token.generate_token,
                max_length=128,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="passwordresettoken",
            name="expires_at",
            field=models.DateTimeField(
                default=apps.accounts.models.password_reset_token.default_expiration,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE accounts_passwordresettoken
                            ADD COLUMN id_uuid uuid;
                        UPDATE accounts_passwordresettoken
                            SET id_uuid = md5(random()::text || clock_timestamp()::text)::uuid;
                        ALTER TABLE accounts_passwordresettoken
                            DROP CONSTRAINT accounts_passwordresettoken_pkey;
                        ALTER TABLE accounts_passwordresettoken
                            DROP COLUMN id;
                        ALTER TABLE accounts_passwordresettoken
                            RENAME COLUMN id_uuid TO id;
                        ALTER TABLE accounts_passwordresettoken
                            ALTER COLUMN id SET NOT NULL;
                        ALTER TABLE accounts_passwordresettoken
                            ADD CONSTRAINT accounts_passwordresettoken_pkey PRIMARY KEY (id);
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="passwordresettoken",
                    name="id",
                    field=models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
            ],
        ),
    ]