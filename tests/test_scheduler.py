"""Testes de app/scheduler.py (ver PLANO.md Fase 16).

Confirma apenas que os dois jobs (scan e retenção) são registrados no
APScheduler com um próximo horário calculado — não espera nenhum
disparo real (o cron de scan roda de hora em hora em dias úteis, e o de
retenção uma vez por dia: esperar um disparo de verdade no teste
levaria horas). O scheduler é desligado ao final para não ficar rodando
em background entre os demais testes da suíte.
"""

from app import scheduler as scheduler_module


async def test_start_registra_os_jobs_de_scan_e_retencao() -> None:
    sched = scheduler_module.start()
    try:
        jobs = {job.id: job for job in sched.get_jobs()}
        assert set(jobs) == {"scan", "retention"}
        assert jobs["scan"].next_run_time is not None
        assert jobs["retention"].next_run_time is not None
    finally:
        sched.shutdown(wait=False)
