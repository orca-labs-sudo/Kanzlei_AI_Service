"""
Job Tracker for AI Service
Tracks progress of AI jobs in-memory
"""
from typing import Dict, Optional
from datetime import datetime, timedelta

# Abgeschlossene/fehlgeschlagene Jobs nach 2h entfernen, laufende nach 24h
_TTL_FINAL = timedelta(hours=2)
_TTL_RUNNING = timedelta(hours=24)


class JobTracker:
    def __init__(self):
        self.jobs: Dict[str, dict] = {}

    def _cleanup(self):
        """Veraltete Jobs entfernen (wird bei jedem create_job aufgerufen)."""
        now = datetime.utcnow()
        expired = [
            jid for jid, job in self.jobs.items()
            if (
                job['status'] in ('completed', 'failed')
                and now - datetime.fromisoformat(job['updated_at']) > _TTL_FINAL
            ) or (
                job['status'] not in ('completed', 'failed')
                and now - datetime.fromisoformat(job['created_at']) > _TTL_RUNNING
            )
        ]
        for jid in expired:
            del self.jobs[jid]

    def create_job(self, job_id: str):
        """Initialize a new job"""
        self._cleanup()
        self.jobs[job_id] = {
            'job_id': job_id,
            'status': 'processing',
            'current_step': 'email_analysis',
            'steps': {
                'email_analysis': {'status': 'processing', 'message': 'E-Mail wird analysiert...'},
                'mandant_creation': {'status': 'pending', 'message': 'Mandant erstellen'},
                'akte_creation': {'status': 'pending', 'message': 'Akte erstellen'},
                'document_upload': {'status': 'pending', 'message': 'Dokumente hochladen'},
                'ticket_creation': {'status': 'pending', 'message': 'Ticket erstellen'}
            },
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

    def update_step(self, job_id: str, step: str, status: str, message: Optional[str] = None):
        """Update a specific step"""
        if job_id not in self.jobs:
            return

        self.jobs[job_id]['current_step'] = step
        self.jobs[job_id]['steps'][step]['status'] = status
        if message:
            self.jobs[job_id]['steps'][step]['message'] = message
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()

    def complete_job(self, job_id: str, akte_id: int, aktenzeichen: str):
        """Mark job as completed"""
        if job_id not in self.jobs:
            return

        self.jobs[job_id]['status'] = 'completed'
        self.jobs[job_id]['akte_id'] = akte_id
        self.jobs[job_id]['aktenzeichen'] = aktenzeichen
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()

    def fail_job(self, job_id: str, error: str):
        """Mark job as failed"""
        if job_id not in self.jobs:
            return

        self.jobs[job_id]['status'] = 'failed'
        self.jobs[job_id]['error'] = error
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job status"""
        return self.jobs.get(job_id)

    def conflict_job(self, job_id: str, conflict_type: str, conflict_message: str, pending_data: dict, candidates: list = None):
        """Pause job waiting for user conflict resolution."""
        if job_id not in self.jobs:
            return
        self.jobs[job_id]['status'] = 'conflict'
        self.jobs[job_id]['conflict_type'] = conflict_type
        self.jobs[job_id]['conflict_message'] = conflict_message
        self.jobs[job_id]['pending_data'] = pending_data
        if candidates:
            self.jobs[job_id]['candidates'] = candidates
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()

    def resume_job(self, job_id: str) -> dict:
        """Get pending_data and reset status to processing for resume."""
        if job_id not in self.jobs:
            return {}
        pending = self.jobs[job_id].pop('pending_data', {})
        self.jobs[job_id]['status'] = 'processing'
        self.jobs[job_id].pop('conflict_type', None)
        self.jobs[job_id].pop('conflict_message', None)
        self.jobs[job_id].pop('candidates', None)
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()
        return pending


# Global instance
job_tracker = JobTracker()
