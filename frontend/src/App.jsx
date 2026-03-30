import React, { useState, useEffect } from 'react';
import FileDropZone from './components/FileDropZone';
import ChatInput from './components/ChatInput';
import AgentTrace from './components/AgentTrace';
import AnswerCard from './components/AnswerCard';
import ChartDisplay from './components/ChartDisplay';
import { createSession, uploadCSV, askQuestion, streamJobEvents, getHistory } from './api/client';

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [uploadData, setUploadData] = useState(null);
  
  const [question, setQuestion] = useState('');
  const [events, setEvents] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [report, setReport] = useState(null);
  const [chart, setChart] = useState(null);
  const [evalMeta, setEvalMeta] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);

  useEffect(() => {
    createSession()
      .then((data) => setSessionId(data.session_id))
      .catch((err) => console.error('Session init failed:', err));
  }, []);

  const handleFileUpload = async (file) => {
    if (!sessionId) return;
    try {
      const data = await uploadCSV(sessionId, file);
      setUploadData({
        filename: file.name,
        uploadId: data.upload_id,
        rowCount: data.row_count,
        colCount: data.col_count
      });
      // clear previous run
      setEvents([]);
      setReport(null);
      setChart(null);
      setErrorInfo(null);
    } catch (err) {
      console.error(err);
      setErrorInfo(err.message);
    }
  };

  const handleSend = async (qText) => {
    if (!sessionId || !uploadData) return;
    setQuestion(qText);
    setIsProcessing(true);
    setEvents([]);
    setReport(null);
    setChart(null);
    setErrorInfo(null);
    setEvalMeta(null);

    try {
      const { job_id } = await askQuestion(sessionId, uploadData.uploadId, qText);
      
      streamJobEvents(
        job_id,
        (ev) => {
          setEvents((prev) => [...prev, ev]);
        },
        (finalData) => {
          setReport(finalData.report);
          setChart(finalData.chart_b64);
          setEvalMeta({ score: finalData.eval_score, iterations: finalData.iterations });
          setIsProcessing(false);
        },
        (err) => {
          console.error(err);
          setErrorInfo('Live stream failed. The worker may have crashed.');
          setIsProcessing(false);
        }
      );
    } catch (err) {
      console.error(err);
      setErrorInfo(err.message);
      setIsProcessing(false);
    }
  };

  return (
    <div className="container" style={{ paddingTop: 'var(--space-64)' }}>
      <header className="flex-col gap-8" style={{ marginBottom: 'var(--space-24)', textAlign: 'center' }}>
        <h1 className="text-hero">Data Analysis</h1>
        <p className="text-body color-muted">Upload a dataset and ask fully autonomous AI agents about it.</p>
      </header>

      <div className="layout-grid">
        {/* Left Column */}
        <div className="flex-col gap-24">
          <FileDropZone onFileUpload={handleFileUpload} fileSummary={uploadData} />
          <ChatInput onSend={handleSend} disabled={!uploadData || isProcessing} />
          
          {errorInfo && (
            <div className="text-body color-error" style={{ textAlign: 'center' }}>
              Error: {errorInfo}
            </div>
          )}
        </div>

        {/* Right Column */}
        <div className="flex-col gap-24">
          {events.length > 0 && <AgentTrace events={events} />}
          {(isProcessing || report) && (
            <AnswerCard 
              report={report} 
              isLoading={isProcessing && !report} 
              evalScore={evalMeta?.score} 
              iterations={evalMeta?.iterations} 
            />
          )}
          {chart && <ChartDisplay chartB64={chart} question={question} />}
        </div>
      </div>
    </div>
  );
}
