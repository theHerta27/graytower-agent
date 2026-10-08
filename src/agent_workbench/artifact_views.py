"""Hash-checked historical views; these never grant permission to execute."""
from .domain._shared import PROFILE, valid_hash


def frozen_candidate(repo, manifest_hash):
    manifest = repo.read_artifact(valid_hash(manifest_hash))
    if (manifest.get('schema_version') != 'candidate-manifest-v1'
            or manifest.get('kind') != 'numeric_config' or manifest.get('profile') != PROFILE):
        raise ValueError('unsupported historical candidate')
    schemas = {'baseline': 'combat-bundle-v2', 'candidate': 'combat-bundle-v2',
               'scenario': 'combat-scenario-v2', 'sources': 'game-sources-v1',
               'schema': 'game-schema-v1', 'rules': 'game-rules-v1',
               'environment': 'worker-environment-v1'}
    for name, schema in schemas.items():
        repo.artifacts.read_ref(manifest[name], schema)
    return {'manifest_hash': manifest_hash, 'manifest': manifest,
            'diff': manifest['diff'], 'validation': manifest['validation']}


def candidate_view(repo, manifest_hash):
    try:
        return repo.get(manifest_hash) | {'execution_compatible': True, 'compatibility_note': ''}
    except ValueError as exc:
        # Only environment/source/version drift permits an archive view. Missing
        # or corrupt artifacts must still fail, rather than masquerade as history.
        if 'fingerprint/content drift' not in str(exc):
            raise
        return frozen_candidate(repo, manifest_hash) | {'execution_compatible': False,
            'compatibility_note': '仅历史回看：当前执行环境与冻结版本不同；新验证需建立新候选，旧报告不变。'}
