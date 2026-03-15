"""
Document Loaders
================

Handles loading of various document formats (text, PDF, DOCX, images).
Extracted from DocumentProcessor for modularity.
"""

import os
import re
import base64
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any, Union

from .. import config
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

# Document loaders with proper initialization
PyPDF2 = None
PDF_AVAILABLE = False
try:
    import PyPDF2 as pypdf2_lib
    PyPDF2 = pypdf2_lib
    PDF_AVAILABLE = True
    logger.debug("PyPDF2 available for PDF processing")
except ImportError:
    logger.warning("PyPDF2 not available - PDF support disabled")

Document = None
DOCX_AVAILABLE = False
try:
    from docx import Document as DocxDocument
    Document = DocxDocument
    DOCX_AVAILABLE = True
    logger.debug("python-docx available for DOCX processing")
except ImportError:
    logger.warning("python-docx not available - DOCX support disabled")

# Try to import monitoring - graceful degradation if not available
try:
    from ..monitoring import timed, counted
except ImportError:
    def timed(_metric_name):  # noqa: E306
        return lambda func: func
    def counted(_metric_name, _labels=None):  # noqa: E306
        return lambda func: func


class DocumentLoaderMixin:
    """
    Mixin providing document loading methods for DocumentProcessor.
    
    Supports text, PDF (with table extraction), DOCX, and image files.
    """
    
    def load_text_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a text file.
        
        Args:
            file_path: Path to text file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        try:
            logger.debug(f"Loading text file: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.debug(f"Loaded {len(content)} characters from text file")
            return True, content
        except Exception as e:
            logger.error(f"Error loading text file: {e}", exc_info=True)
            return False, str(e)
    
    def load_pdf_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a PDF file with enhanced table extraction and improved text extraction.
        
        Uses pdfplumber for better table extraction if available,
        falls back to PyPDF2 for basic text extraction.
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        if not PDF_AVAILABLE:
            logger.error("PyPDF2 not installed")
            return False, "PyPDF2 not installed"
        
        try:
            logger.info(f"Loading PDF file: {file_path}")
            file_size = os.path.getsize(file_path)
            logger.debug(f"PDF file size: {file_size:,} bytes")
            
            # Try to use pdfplumber for better table extraction
            pdfplumber = None  # Initialize to None
            try:
                import pdfplumber as pdf_lib
                pdfplumber = pdf_lib
                logger.info("pdfplumber available - using enhanced table extraction")
            except ImportError:
                logger.warning("pdfplumber not available - will use basic PyPDF2 extraction")
            
            text = ""
            extraction_method = "unknown"
            
            if pdfplumber is not None:
                # Enhanced extraction with pdfplumber (handles tables better)
                try:
                    logger.debug("Attempting pdfplumber extraction...")
                    with pdfplumber.open(file_path) as pdf:
                        num_pages = len(pdf.pages)
                        logger.info(f"PDF has {num_pages} pages (using pdfplumber)")
                        
                        pages_with_tables = 0
                        total_tables = 0
                        
                        for page_num, page in enumerate(pdf.pages, 1):
                            logger.debug(f"Processing page {page_num}/{num_pages}...")
                            
                            # Extract regular text
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                                logger.debug(f"  Page {page_num}: extracted {len(page_text)} characters of text")
                            else:
                                logger.warning(f"  Page {page_num}: no text extracted")
                            
                            # Extract tables
                            try:
                                tables = page.extract_tables()
                                if tables:
                                    pages_with_tables += 1
                                    logger.info(f"  Page {page_num}: Found {len(tables)} table(s)")
                                    total_tables += len(tables)
                                    
                                    for table_idx, table in enumerate(tables, 1):
                                        if not table:
                                            logger.warning(f"    Table {table_idx}: Empty table")
                                            continue
                                        text += f"\n[Table {table_idx} on page {page_num}]\n"
                                        
                                        # Convert table to text format with better handling
                                        rows_added = 0
                                        for row_idx, row in enumerate(table):
                                            if not row:  # Skip empty rows
                                                continue
                                            # Filter out None values and join cells
                                            row_text = " | ".join([str(cell).strip() if cell else "" for cell in row])
                                            if row_text.strip():  # Only add non-empty rows
                                                text += row_text + "\n"
                                                rows_added += 1
                                                
                                        text += "\n"
                                        logger.debug(f"    Table {table_idx}: {len(table)} total rows, {rows_added} non-empty rows added")
                                else:
                                    logger.debug(f"  Page {page_num}: No tables found")
                            except Exception as table_error:
                                logger.error(f"  Page {page_num}: Error extracting tables: {table_error}")
                    
                    extraction_method = "pdfplumber"
                    logger.info("pdfplumber extraction complete:")
                    logger.info(f"  - Total pages: {num_pages}")
                    logger.info(f"  - Pages with tables: {pages_with_tables}")
                    logger.info(f"  - Total tables: {total_tables}")
                    logger.info(f"  - Total characters extracted: {len(text):,}")
                    
                    # Validate extraction quality
                    if len(text) < 100:
                        logger.warning(f"pdfplumber extraction yielded very little text ({len(text)} chars), trying PyPDF2 as backup...")
                        raise ValueError("Insufficient text extracted with pdfplumber")
                    
                except Exception as plumber_error:
                    logger.warning(f"pdfplumber extraction failed: {plumber_error}")
                    logger.warning("Falling back to PyPDF2 extraction...")
                    text = ""  # Reset for PyPDF2 attempt
                    extraction_method = "pdfplumber_failed"
            
            # Fallback to PyPDF2 (basic extraction) - if pdfplumber not available or failed
            if not text or extraction_method == "pdfplumber_failed":
                logger.info("Using PyPDF2 for text extraction...")
                text = ""
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    num_pages = len(pdf_reader.pages)
                    logger.info(f"PDF has {num_pages} pages (using PyPDF2)")
                    
                    for page_num, page in enumerate(pdf_reader.pages, 1):
                        logger.debug(f"Processing page {page_num}/{num_pages} with PyPDF2...")
                        try:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                                logger.debug(f"  Page {page_num}: extracted {len(page_text)} characters")
                            else:
                                logger.warning(f"  Page {page_num}: no text extracted")
                        except Exception as page_error:
                            logger.error(f"  Page {page_num}: Error extracting text: {page_error}")
                
                extraction_method = "PyPDF2"
                logger.info(f"PyPDF2 extraction complete: {len(text):,} characters")
            
            # Final validation
            if not text.strip():
                error_msg = "PDF extraction resulted in empty text - file may be image-based (scanned) or password-protected."
                logger.error(error_msg)
                logger.error(f"File details: size={file_size:,} bytes, path={file_path}")
                return False, error_msg
            
            if len(text) < 100:
                logger.warning(f"PDF extraction yielded very little text: {len(text)} characters (expected more based on file size)")
            
            logger.info(f"PDF extraction successful using {extraction_method}: {len(text):,} characters extracted")
            return True, text
            
        except Exception as e:
            logger.error(f"Error loading PDF: {e}", exc_info=True)
            return False, str(e)
    
    def _load_pdf_with_pages(self, file_path: str) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
        """
        Load PDF with page-by-page tracking for enhanced citations.
        
        Returns page data with page numbers and section titles instead of
        concatenated text.
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Tuple of (success: bool, pages_data_or_error)
            On success: List of dicts with keys: page_number, text, section_title
            On failure: Error message string
        """
        if not PDF_AVAILABLE:
            logger.error("PyPDF2 not installed")
            return False, "PyPDF2 not installed"
        
        try:
            logger.info(f"Loading PDF with page tracking: {file_path}")
            
            # Try pdfplumber first
            pdfplumber = None
            try:
                import pdfplumber as pdf_lib
                pdfplumber = pdf_lib
                logger.info("Using pdfplumber for page-by-page extraction")
            except ImportError:
                logger.warning("pdfplumber not available, using PyPDF2")
            
            pages_data = []
            
            if pdfplumber is not None:
                # Use pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    num_pages = len(pdf.pages)
                    logger.info(f"PDF has {num_pages} pages")
                    
                    for page_num, page in enumerate(pdf.pages, 1):
                        logger.debug(f"Processing page {page_num}/{num_pages}...")
                        
                        # Extract text
                        page_text = page.extract_text() or ""
                        
                        # Extract tables and append to text
                        try:
                            tables = page.extract_tables()
                            if tables:
                                logger.debug(f"  Page {page_num}: Found {len(tables)} table(s)")
                                for table_idx, table in enumerate(tables, 1):
                                    if table:
                                        page_text += f"\n[Table {table_idx}]\n"
                                        for row in table:
                                            if row:
                                                row_text = " | ".join([str(cell).strip() if cell else "" for cell in row])
                                                if row_text.strip():
                                                    page_text += row_text + "\n"
                                        page_text += "\n"
                        except Exception as e:
                            logger.warning(f"  Page {page_num}: Error extracting tables: {e}")
                        
                        if page_text and len(page_text.strip()) > 0:
                            # Extract section title
                            section_title = self._extract_section_title(page_text)
                            
                            pages_data.append({
                                'page_number': page_num,
                                'text': page_text,
                                'section_title': section_title
                            })
                            
                            logger.debug(f"  Page {page_num}: {len(page_text)} chars, section: {section_title or 'None'}")
                        else:
                            logger.warning(f"  Page {page_num}: No text extracted")
            
            else:
                # Fallback to PyPDF2
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    num_pages = len(pdf_reader.pages)
                    logger.info(f"PDF has {num_pages} pages (PyPDF2)")
                    
                    for page_num, page in enumerate(pdf_reader.pages, 1):
                        page_text = page.extract_text() or ""
                        
                        if page_text and len(page_text.strip()) > 0:
                            section_title = self._extract_section_title(page_text)
                            
                            pages_data.append({
                                'page_number': page_num,
                                'text': page_text,
                                'section_title': section_title
                            })
                            
                            logger.debug(f"  Page {page_num}: {len(page_text)} chars, section: {section_title or 'None'}")
            
            logger.info(f"Extracted {len(pages_data)} pages with metadata")
            
            # Validate
            if not pages_data:
                return False, "No pages with text extracted from PDF"
            
            return True, pages_data
            
        except Exception as e:
            logger.error(f"Error loading PDF with pages: {e}", exc_info=True)
            return False, str(e)
    
    def load_docx_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a DOCX file with enhanced error handling.
        
        Extracts text from both paragraphs and tables in the document.
        
        Args:
            file_path: Path to DOCX file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        if not DOCX_AVAILABLE:
            logger.error("python-docx not installed")
            return False, "python-docx not installed"
        
        try:
            logger.debug(f"Loading DOCX file: {file_path}")
            
            # Check if file exists
            if not os.path.exists(file_path):
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                return False, error_msg
            
            # Check file size
            file_size = os.path.getsize(file_path)
            logger.debug(f"DOCX file size: {file_size} bytes")
            
            if file_size == 0:
                logger.error("File is empty (0 bytes)")
                return False, "File is empty (0 bytes)"
            
            # Try to open the document
            try:
                doc = Document(file_path)
            except Exception as doc_error:
                error_msg = f"Failed to open DOCX file: {str(doc_error)}"
                logger.error(error_msg, exc_info=True)
                return False, f"{error_msg}. File might be corrupted or password-protected."
            
            # Extract text from paragraphs
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:  # Only include non-empty paragraphs
                    paragraphs.append(text)
            
            # Also extract text from tables
            tables_text = []
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if text:
                            tables_text.append(text)
            
            # Combine all text
            all_text = paragraphs + tables_text
            text = "\n".join(all_text)
            
            logger.debug(f"Extracted {len(paragraphs)} paragraphs and {len(tables_text)} table cells")
            logger.debug(f"Total text length: {len(text)} characters")
            
            if not text or len(text.strip()) < 10:
                error_msg = f"Document appears to be empty or has very little text (only {len(text)} characters)"
                logger.warning(error_msg)
                return False, f"{error_msg}. Check if document has actual content."
            
            return True, text
            
        except Exception as e:
            logger.error(f"Error loading DOCX: {e}", exc_info=True)
            return False, f"Error loading DOCX: {str(e)}"
    
    def _extract_section_title(self, page_text: str) -> Optional[str]:
        """
        Extract likely section title from page start.
        
        Looks at the first few lines of a page to identify section headers.
        
        Args:
            page_text: Text content of a page
        
        Returns:
            Section title string or None if no title found
        """
        if not page_text:
            return None
        
        lines = page_text.strip().split('\n')
        
        # Check first 5 lines for potential title
        for line in lines[:5]:
            line = line.strip()
            
            # Skip empty lines or very short lines
            if not line or len(line) < 3:
                continue
            
            # Skip numbered lines (e.g., "1. Introduction")
            if re.match(r'^\d+\.', line):
                continue
            
            # Check if looks like a title
            if len(line) < 100:
                if line.endswith(':'):
                    return line.rstrip(':')
                elif line.istitle() and len(line.split()) >= 2:
                    return line
                elif line.isupper() and len(line.split()) >= 2:
                    return line
        
        return None
    
    def load_image_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Load an image file by generating a text description via a vision model.

        Args:
            file_path: Path to the image file (.png, .jpg, .jpeg, .gif, .webp)

        Returns:
            Tuple of (success: bool, description_or_error: str)
        """
        try:
            logger.info(f"Loading image file: {file_path}")

            with open(file_path, 'rb') as f:
                image_data = f.read()

            image_b64 = base64.b64encode(image_data).decode('utf-8')

            vision_model = ollama_client.get_vision_model()
            if not vision_model:
                return False, "No vision model available for image processing"

            success, description = ollama_client.describe_image(vision_model, image_b64)
            if not success:
                return False, f"Failed to describe image: {description}"

            filename = os.path.basename(file_path)
            content = f"Image: {filename}\n\n{description}"
            logger.info(f"Image loaded: {len(content)} characters from {filename}")
            return True, content

        except Exception as e:
            logger.error(f"Error loading image file: {e}", exc_info=True)
            return False, str(e)

    @timed('rag.load_document')
    @counted('rag.document_loads')
    def load_document(self, file_path: str) -> Tuple[bool, str]:
        """
        Load a document based on its extension.
        
        Args:
            file_path: Path to document file
        
        Returns:
            Tuple of (success: bool, content_or_error: str)
        """
        ext = Path(file_path).suffix.lower()
        logger.debug(f"Loading document with extension: {ext}")

        if ext == '.txt' or ext == '.md':
            return self.load_text_file(file_path)
        elif ext == '.pdf':
            return self.load_pdf_file(file_path)
        elif ext == '.docx':
            return self.load_docx_file(file_path)
        elif ext in config.SUPPORTED_IMAGE_EXTENSIONS:
            return self.load_image_file(file_path)
        else:
            error_msg = f"Unsupported file type: {ext}"
            logger.error(error_msg)
            return False, error_msg
