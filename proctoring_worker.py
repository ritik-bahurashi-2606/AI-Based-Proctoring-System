import os
import time

from celery import Celery

from app import app, _process_proctoring_frame, _release_proctoring_reservation


broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
celery_app = Celery('myproctor_proctoring', broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_default_queue='proctoring-0',
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    broker_transport_options={'visibility_timeout': 3600},
    accept_content=['json'],
    task_serializer='json',
    result_serializer='json',
)


@celery_app.task(bind=True, name='proctoring.process_frame', acks_late=True)
def process_proctoring_frame_task(self, payload):
    started_at = time.perf_counter()
    started_wall_time = time.time()
    job_id = self.request.id
    try:
        with app.app_context():
            result = _process_proctoring_frame(
                payload['img_data'],
                payload['testid'],
                payload['voice_db'],
                payload['uid'],
                payload['email'],
                payload['name'],
                job_id=job_id,
            )
        result.update({
            'uid': payload['uid'],
            'testid': payload['testid'],
            'queue_wait_ms': max(
                0.0,
                (started_wall_time - payload.get('enqueued_at', started_wall_time)) * 1000,
            ),
        })
        app.logger.info(
            'Proctoring job completed: job=%s uid=%s test=%s queue_wait_ms=%.2f '
            'cv_ms=%.2f worker_ms=%.2f',
            job_id, payload['uid'], payload['testid'],
            result['queue_wait_ms'], result['cv_duration_ms'],
            (time.perf_counter() - started_at) * 1000,
        )
        return result
    except Exception:
        app.logger.exception(
            'Proctoring worker failed: job=%s uid=%s test=%s',
            job_id, payload.get('uid'), payload.get('testid'),
        )
        raise
    finally:
        _release_proctoring_reservation(job_id)
