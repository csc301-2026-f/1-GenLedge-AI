"""Composition seam for A/B/C and the explicit single-process D2 worker."""
import atexit
import importlib
import os
from concurrent.futures import ThreadPoolExecutor

from .routes import bp


def init_mappings(app):
    app.register_blueprint(bp)
    factory = app.config.get('MAPPING_SERVICE_FACTORY')
    reference = os.environ.get('GENLEDGE_MAPPING_RUNTIME_FACTORY')
    if factory is None and reference:
        module, name = reference.split(':', 1)
        factory = getattr(importlib.import_module(module), name)
    if factory is None:
        return  # Auth and the rest of the application remain usable; routes return 503.
    service = factory(app)
    dispatch = app.config.get('MAPPING_DISPATCH')
    if dispatch is None:
        # Opt in explicitly; deployed workers supply a durable queue dispatcher.
        if os.environ.get('GENLEDGE_AGENT_INLINE_RUN') != '1':
            raise RuntimeError('Configure MAPPING_DISPATCH or set GENLEDGE_AGENT_INLINE_RUN=1 for D2.')
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='routing')
        atexit.register(executor.shutdown, wait=True)
        app.extensions['mapping_executor'] = executor

        def execute(owner, job_id):
            with app.app_context():
                service.execute(owner, job_id)

        def dispatch(owner, job_id):
            executor.submit(execute, owner, job_id)

    app.extensions['mapping_service'] = service
    app.extensions['mapping_dispatch'] = dispatch
    app.logger.info('Routing model mode: %s', service.model_mode)
