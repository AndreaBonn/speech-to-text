from sbobina.web.job_models import JobRecord


def reader_title(record: JobRecord) -> str:
    """Source file name first, then the subject, then a dated fallback.

    Mirrors ``jobTitle()`` in jobs.js so the queue row and the reader page
    never disagree on what to call the same job.
    """
    if record.source_name:
        return record.source_name
    if record.config.subject:
        return record.config.subject
    return f"Lezione del {record.created_at.strftime('%d/%m/%Y')}"
