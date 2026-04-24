from __future__ import annotations

import os
from pathlib import Path
import py7zr
import structlog

log = structlog.get_logger(__name__)

async def create_split_archive(source_file: Path, part_size_mb: int = 1900) -> list[Path]:
    """
    Creates a multi-part 7z archive from a source file.
    Default part size is slightly under 2GB (1900MB).
    """
    if not source_file.exists():
        raise FileNotFoundError(f"Source file {source_file} not found")

    output_dir = source_file.parent
    archive_name = f"{source_file.stem}.7z"
    archive_path = output_dir / archive_name
    
    # py7zr supports multi-volume archives
    # We need to use the 'filters' and 'volume_limit'
    
    # Converting MB to bytes
    volume_limit = part_size_mb * 1024 * 1024
    
    log.info("creating_split_archive", 
             source=str(source_file), 
             archive=str(archive_path), 
             part_size_mb=part_size_mb)

    # Note: py7zr is synchronous, so we run it in a thread if needed, 
    # but here we'll just run it as is or wrap it.
    import asyncio
    
    def _create():
        # Using multivolumefile via py7zr
        # However, simple splitting might be easier for the user to extract
        # but the user specifically asked for an archive format.
        
        with py7zr.SevenZipFile(archive_path, 'w', volume_limit=volume_limit) as archive:
            archive.write(source_file, arcname=source_file.name)
            
    await asyncio.to_thread(_create)
    
    # Find all created parts
    # py7zr names them .7z.001, .7z.002, etc.
    parts = sorted(list(output_dir.glob(f"{source_file.stem}.7z*")))
    
    log.info("archive_split_complete", parts_count=len(parts))
    return parts
