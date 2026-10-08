import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import CampPage from './CampPage';
import CodeRepair from './CodeRepair';
import TestPlay from './TestPlay';
import './styles.css';

createRoot(document.getElementById('root')!).render(<StrictMode>{location.pathname === '/camp' ? <CampPage /> : location.pathname === '/code-repair' ? <CodeRepair /> : location.pathname==='/test-play'?<TestPlay/>:<App />}</StrictMode>);
