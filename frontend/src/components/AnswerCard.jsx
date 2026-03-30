import React from 'react';
import ReactMarkdown from 'react-markdown';

export default function AnswerCard({ report, isLoading, evalScore, iterations }) {
  if (!report && !isLoading) return null;

  return (
    <div className="card" style={{ position: 'relative' }}>
      <div className="flex-row" style={{ justifyContent: 'space-between', marginBottom: 'var(--space-16)' }}>
        <div className="text-heading">Answer</div>
        {evalScore !== undefined && (
          <div className="flex-row gap-8">
            {iterations && <span className="text-caption color-muted">{iterations} iterations</span>}
            <span className="text-caption color-success" style={{ padding: '2px 8px', borderRadius: 'var(--radius-pill)', backgroundColor: '#22C55E15' }}>
              Score: {evalScore.toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex-col gap-12">
          <div className="skeleton" style={{ height: '14px', width: '100%' }} />
          <div className="skeleton" style={{ height: '14px', width: '90%' }} />
          <div className="skeleton" style={{ height: '14px', width: '95%' }} />
          <div className="skeleton" style={{ height: '14px', width: '60%' }} />
        </div>
      ) : (
        <div className="prose">
          <ReactMarkdown>{report}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
