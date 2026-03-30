import React, { useRef, useState } from 'react';

export default function FileDropZone({ onFileUpload, fileSummary }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileUpload(e.target.files[0]);
    }
  };

  if (fileSummary) {
    return (
      <div className="flex-row gap-12" style={{ padding: 'var(--space-12) var(--space-16)', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-pill)' }}>
        <span className="font-mono color-primary">{fileSummary.filename}</span>
        <span className="color-subtle text-caption">•</span>
        <span className="color-muted text-caption">{fileSummary.rowCount} rows</span>
        <span className="color-subtle text-caption">•</span>
        <span className="color-muted text-caption">{fileSummary.colCount} cols</span>
      </div>
    );
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        width: '100%',
        border: `1px dashed ${isDragOver ? 'var(--accent)' : 'var(--border-color)'}`,
        backgroundColor: isDragOver ? 'var(--accent-muted)' : 'var(--surface)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-48) var(--space-24)',
        textAlign: 'center',
        cursor: 'pointer',
        transform: isDragOver ? 'scale(1.01)' : 'scale(1)',
        transition: 'all 150ms ease'
      }}
    >
      <input 
        type="file" 
        accept=".csv"
        ref={inputRef} 
        onChange={handleChange} 
        style={{ display: 'none' }} 
      />
      <p className="text-body color-muted">
        <span className="color-accent" style={{ color: 'var(--accent)' }}>Upload a CSV</span> or drag and drop
      </p>
    </div>
  );
}
