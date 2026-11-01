"""Attributes become shared, standalone rows.

Schema: Subcategory gains an ``attributes`` M2M to ProductAttribute and the
old ``ProductAttribute.subcategory`` foreign key is dropped; ``key`` becomes
globally unique so one key always means one attribute.

Data: existing rows are preserved. Each attribute is linked to its old
subcategory through the new M2M; rows that reused the same key on different
subcategories are folded into the earliest one (its name/flags win), which
absorbs the duplicates' subcategory selections and choices, and historical
``OrderItemOption`` snapshots are re-pointed to the surviving rows.

The reverse migration is best-effort: sharing cannot be expressed by the old
one-subcategory-per-attribute shape, so every linked subcategory gets its own
copy of the attribute (with the canonical name and flags).
"""

from django.db import migrations, models


def merge_shared_attributes(apps, schema_editor):
    """Link existing attributes to their subcategory and merge same-key
    duplicates into one shared attribute (earliest row wins)."""
    Subcategory = apps.get_model("products", "Subcategory")
    ProductAttribute = apps.get_model("products", "ProductAttribute")
    AttributeChoice = apps.get_model("products", "AttributeChoice")
    OrderItemOption = apps.get_model("orders", "OrderItemOption")

    canonical_by_key = {}
    for attribute in ProductAttribute.objects.order_by("id"):
        canonical = canonical_by_key.setdefault(attribute.key, attribute)
        if canonical.pk == attribute.pk:
            if attribute.subcategory_id:
                owner = Subcategory.objects.filter(pk=attribute.subcategory_id).first()
                if owner is not None:
                    owner.attributes.add(attribute)
            continue

        # A later row reused the same key: fold it into the canonical one.
        if attribute.subcategory_id:
            owner = Subcategory.objects.filter(pk=attribute.subcategory_id).first()
            if owner is not None:
                owner.attributes.add(canonical)
        if canonical.input_type == attribute.input_type == "select":
            for choice in list(attribute.choices.all()):
                surviving = AttributeChoice.objects.filter(
                    attribute_id=canonical.pk, key=choice.key
                ).first()
                if surviving is None:
                    # Move the choice to the canonical attribute; historical
                    # snapshots keep pointing at the same row.
                    AttributeChoice.objects.filter(pk=choice.pk).update(
                        attribute_id=canonical.pk
                    )
                else:
                    # Keep the canonical choice and re-point historical
                    # snapshots before dropping the duplicate row.
                    OrderItemOption.objects.filter(choice_id=choice.pk).update(
                        choice_id=surviving.pk
                    )
                    choice.delete()
        # Historical snapshots are key/label-based; re-point the FK so admin
        # traceability survives the merge.
        OrderItemOption.objects.filter(attribute_id=attribute.pk).update(
            attribute_id=canonical.pk
        )
        attribute.delete()


def split_shared_attributes(apps, schema_editor):
    """Best-effort reverse: the previous schema could not express sharing,
    so every linked subcategory gets its own copy of the attribute."""
    ProductAttribute = apps.get_model("products", "ProductAttribute")
    AttributeChoice = apps.get_model("products", "AttributeChoice")

    for attribute in list(ProductAttribute.objects.all()):
        subcategory_ids = list(attribute.subcategories.values_list("pk", flat=True))
        if not subcategory_ids:
            continue
        attribute.subcategory_id = subcategory_ids[0]
        attribute.save(update_fields=["subcategory"])
        for subcategory_id in subcategory_ids[1:]:
            choices = list(attribute.choices.all())
            clone = ProductAttribute.objects.create(
                subcategory_id=subcategory_id,
                key=attribute.key,
                name=attribute.name,
                input_type=attribute.input_type,
                is_required=attribute.is_required,
                is_active=attribute.is_active,
            )
            for choice in choices:
                AttributeChoice.objects.create(
                    attribute=clone,
                    key=choice.key,
                    label=choice.label,
                    price_delta=choice.price_delta,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0007_productattribute_attributechoice_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='productattribute',
            name='uniq_attribute_key_per_subcategory',
        ),
        migrations.AddField(
            model_name='subcategory',
            name='attributes',
            field=models.ManyToManyField(blank=True, help_text="The attributes whose options apply to this subcategory's products (one attribute may be selected by several subcategories).", related_name='subcategories', to='products.productattribute', verbose_name='Attributes'),
        ),
        migrations.RunPython(merge_shared_attributes, split_shared_attributes),
        migrations.AlterField(
            model_name='productattribute',
            name='key',
            field=models.CharField(help_text='Stable API identifier (e.g. car_type); unique across the shop so the same key means the same attribute on every subcategory.', max_length=64, unique=True, verbose_name='Key'),
        ),
        migrations.RemoveField(
            model_name='productattribute',
            name='subcategory',
        ),
    ]
