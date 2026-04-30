import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Standings from './pages/Standings';
import RacePace from './pages/RacePace';
import Telemetry from './pages/Telemetry';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Standings />} />
          <Route path="/race-pace" element={<RacePace />} />
          <Route path="/telemetry" element={<Telemetry />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
