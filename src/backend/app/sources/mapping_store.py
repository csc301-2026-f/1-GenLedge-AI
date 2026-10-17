"""Persist mapping definitions without interpreting the downstream mapping language."""
import sqlalchemy as sa

fields = sa.table('intake_fields', sa.column('scope_id'), sa.column('batch_id'),
    sa.column('collection_id'), sa.column('field_id'), sa.column('path', sa.JSON),
    sa.column('kinds', sa.JSON), sa.column('matchable', sa.Boolean))
mappings = sa.table('source_mappings', sa.column('scope_id'), sa.column('source_id'),
    sa.column('mapping_id'), sa.column('collection_id'), sa.column('field_ids', sa.JSON),
    sa.column('definition', sa.JSON), sa.column('status'), sa.column('valid_batch_id'), sa.column('checked_batch_id'))


def reconcile(connection, scope_id, source_id, batch_id):
    """Run under the publication source lock, in the same transaction."""
    saved = connection.execute(sa.select(mappings).where(mappings.c.scope_id == scope_id,
        mappings.c.source_id == source_id)).mappings().all()
    current = {row['field_id']: row for row in connection.execute(sa.select(fields).where(
        fields.c.scope_id == scope_id, fields.c.batch_id == batch_id)).mappings()}
    for mapping in saved:
        previous = {row['field_id']: row for row in connection.execute(sa.select(fields).where(
            fields.c.scope_id == scope_id, fields.c.batch_id == mapping['valid_batch_id'],
            fields.c.collection_id == mapping['collection_id'])).mappings()}
        valid = True
        for field_id in mapping['field_ids']:
            before, after = previous.get(field_id), current.get(field_id)
            if (not before or not after or not after['matchable'] or
                    after['collection_id'] != mapping['collection_id'] or
                    (after['kinds'] and after['kinds'] != before['kinds'])):
                valid = False
                break
        values = dict(status='valid' if valid else 'needs_review', checked_batch_id=batch_id)
        if valid:
            values['valid_batch_id'] = batch_id
        connection.execute(mappings.update().where(mappings.c.scope_id == scope_id,
            mappings.c.source_id == source_id, mappings.c.mapping_id == mapping['mapping_id']).values(**values))


def public_mapping(row):
    return {'mappingId': row['mapping_id'], 'collectionId': row['collection_id'],
            'fieldIds': row['field_ids'], 'definition': row['definition'], 'status': row['status'],
            'validBatchId': row['valid_batch_id'], 'checkedBatchId': row['checked_batch_id']}
