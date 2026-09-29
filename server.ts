import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import cors from 'cors';
import nunjucks from 'nunjucks';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Polyfills for Python string methods used in Jinja templates
if (!(String.prototype as any).endswith) {
  (String.prototype as any).endswith = function (suffix: string) {
    return this.endsWith(suffix);
  };
}
if (!(String.prototype as any).rsplit) {
  (String.prototype as any).rsplit = function (sep: string, maxsplit?: number) {
    const parts = this.split(sep);
    if (maxsplit === 1 && parts.length > 1) {
      return [parts.slice(0, -1).join(sep), parts[parts.length - 1]];
    }
    return parts;
  };
}

const app = express();
const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '0.0.0.0';

// Setup Nunjucks
const env = nunjucks.configure(path.join(__dirname, 'templates'), {
  autoescape: true,
  express: app,
  watch: false,
  noCache: true
});

// Nunjucks global functions and filters
env.addGlobal('url_for', (endpoint: string, kwargs?: any) => {
  if (endpoint === 'static') {
    let fn = kwargs && typeof kwargs === 'object' ? (kwargs.filename || '') : (kwargs || '');
    return '/static/' + String(fn).replace(/^\//, '');
  }
  const routeMap: Record<string, string> = {
    home: '/home',
    control_panel: '/control_panel',
    valve_specs_page: '/valve-specs',
    index: '/index',
    training_page: '/training',
    filter: '/filter',
    dashboard: '/dashboard',
    defect_dashboard: '/defect_dashboard',
    download_daily_report: '/download_daily_report',
    profile: '/profile',
    logout: '/logout',
    login: '/login',
    overview: '/overview',
    flow_editor: '/flow-editor'
  };
  return routeMap[endpoint] || `/${endpoint}`;
});

env.addGlobal('current_year', new Date().getFullYear());

// Helper function to create a Session wrapper with .get() method matching Jinja2
function createSessionWrapper(sess: any) {
  return new Proxy(sess || {}, {
    get(target, prop, receiver) {
      if (prop === 'get') {
        return (key: string, defaultValue?: any) => {
          return target[key] !== undefined ? target[key] : defaultValue;
        };
      }
      return Reflect.get(target, prop, receiver);
    }
  });
}

// Middleware
app.use(cors());
app.use(cookieParser());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(
  session({
    secret: process.env.SESSION_SECRET || 'valve-inspection-secret-key-rane-group',
    resave: false,
    saveUninitialized: true,
    cookie: { secure: false, maxAge: 8 * 60 * 60 * 1000 }
  })
);

// Populate view locals
app.use((req, res, next) => {
  // Ensure default demo user so user is not blocked on any page
  if (!req.session.user) {
    req.session.user = 'admin';
    req.session.role = 'ADMIN';
    req.session.location = 'Plant P2';
  }
  res.locals.session = createSessionWrapper(req.session);
  res.locals.current_year = new Date().getFullYear();
  next();
});

// Static directories
app.use('/static', express.static(path.join(__dirname, 'static')));
app.use(express.static(path.join(__dirname, 'static')));
app.use('/uploads', express.static(path.join(__dirname, 'static', 'uploads')));
app.use(
  '/golden_library',
  express.static(path.join(__dirname, 'static', 'Golden Libraries', 'GoldenLibrary'))
);
app.use(
  '/defect_library',
  express.static(path.join(__dirname, 'static', 'Golden Libraries', 'DefectLibrary'))
);
app.use('/inspections', express.static(path.join(__dirname, 'inspections')));
app.use('/dataset', express.static(path.join(__dirname, 'dataset')));

// Favicon
app.get('/favicon.ico', (req, res) => res.status(204).end());

// ================= DATA LAYER (IN-MEMORY MOCK STORE) =================
interface InspectionRecord {
  id: string;
  inspection_id: string;
  part_number: string;
  part_name: string;
  image_name: string;
  result: 'Accepted' | 'Rejected';
  ssim_score: number;
  defect_type: string | null;
  best_match: string;
  location: string;
  shifts: string;
  timestamp: string;
  operator: string;
}

const PART_NAMES: Record<string, string> = {
  '48465': 'Gamma Exhaust',
  '48460': 'Gamma Inlet',
  '46152': 'Kappa 1.2L Inlet',
  '46157': 'Kappa 1.2L Exhaust',
  '46153': 'Kappa 1.2L Exhaust',
  '48290': 'TGDI 1L Inlet',
  '48295': 'TGDI 1L Exhaust',
  '49020': 'TGDI 1.5L Inlet'
};

const DEFECT_TYPES = [
  'Face Damage',
  'Head Damage',
  'Seat Damage',
  'Neck Damage',
  'Stem Damage',
  'Groove Damage',
  'End Chamfer',
  'Tip End',
  'Bent Valve',
  'Crack',
  'Scratch',
  'Discoloration',
  'Radius Damage'
];

const LOCATIONS = ['Plant P2', 'Plant P3', 'Plant P4'];
const SHIFTS = ['Shift A', 'Shift B', 'Shift C'];

// Parse Valve Specs from Valve_Details.csv
const valveSpecsMap: Record<string, Record<string, string>> = {};
try {
  const csvPath = path.join(__dirname, 'Valve_Details.csv');
  if (fs.existsSync(csvPath)) {
    const csvContent = fs.readFileSync(csvPath, 'utf-8');
    const lines = csvContent.split('\n').filter((l) => l.trim().length > 0);
    if (lines.length > 1) {
      const headers = lines[0].split(',').map((h) => h.trim());
      for (let i = 1; i < lines.length; i++) {
        // Simple CSV splitter respecting commas
        const cols = lines[i].split(',').map((c) => c.trim());
        const partNo = cols[0];
        if (partNo) {
          const rowObj: Record<string, string> = {};
          headers.forEach((h, idx) => {
            rowObj[h] = cols[idx] || '';
          });
          valveSpecsMap[partNo] = rowObj;
        }
      }
    }
  }
} catch (e) {
  console.warn('Could not parse Valve_Details.csv:', e);
}

// In-Memory Inspection Database
const inspectionsDB: InspectionRecord[] = [];

// Seed realistic inspection data across Today, Week, Month, and Past
function seedInspections() {
  const now = new Date();
  let idCounter = 1;

  // Helper to create timestamp offset
  const createDate = (daysAgo: number, hour: number, minute: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() - daysAgo);
    d.setHours(hour, minute, Math.floor(Math.random() * 60), 0);
    return d.toISOString();
  };

  const parts = Object.keys(PART_NAMES);

  // Generate 28 inspections for Today
  for (let i = 0; i < 28; i++) {
    const isRejected = i % 7 === 0; // ~4 rejected, 24 accepted
    const partNo = parts[i % parts.length];
    const shift = i < 10 ? 'Shift A' : i < 20 ? 'Shift B' : 'Shift C';
    const hour = i < 10 ? 7 + Math.floor(i * 0.7) : i < 20 ? 15 + Math.floor((i - 10) * 0.7) : 23;
    const defect = isRejected ? DEFECT_TYPES[i % DEFECT_TYPES.length] : null;
    const ssim = isRejected ? 0.68 + Math.random() * 0.15 : 0.92 + Math.random() * 0.07;

    inspectionsDB.push({
      id: `INS-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(idCounter++).padStart(4, '0')}`,
      inspection_id: `INS-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(idCounter).padStart(4, '0')}`,
      part_number: partNo,
      part_name: PART_NAMES[partNo],
      image_name: `IMG_${partNo}_${isRejected ? 'DEFECT' : 'PASS'}_${i}.jpg`,
      result: isRejected ? 'Rejected' : 'Accepted',
      ssim_score: parseFloat(ssim.toFixed(3)),
      defect_type: defect,
      best_match: `${partNo}_master.jpg`,
      location: LOCATIONS[i % LOCATIONS.length],
      shifts: shift,
      timestamp: createDate(0, hour, (i * 13) % 60),
      operator: 'Operator 1'
    });
  }

  // Generate 45 inspections for past 7 days
  for (let i = 1; i <= 7; i++) {
    for (let j = 0; j < 6; j++) {
      const isRejected = (i + j) % 5 === 0;
      const partNo = parts[(i + j) % parts.length];
      const shift = SHIFTS[j % 3];
      const defect = isRejected ? DEFECT_TYPES[(i * 3 + j) % DEFECT_TYPES.length] : null;
      const ssim = isRejected ? 0.65 + Math.random() * 0.18 : 0.91 + Math.random() * 0.08;

      inspectionsDB.push({
        id: `INS-${String(idCounter++).padStart(6, '0')}`,
        inspection_id: `INS-${String(idCounter).padStart(6, '0')}`,
        part_number: partNo,
        part_name: PART_NAMES[partNo],
        image_name: `IMG_${partNo}_${isRejected ? 'REJ' : 'ACC'}_${i}_${j}.jpg`,
        result: isRejected ? 'Rejected' : 'Accepted',
        ssim_score: parseFloat(ssim.toFixed(3)),
        defect_type: defect,
        best_match: `${partNo}_master.jpg`,
        location: LOCATIONS[(i + j) % LOCATIONS.length],
        shifts: shift,
        timestamp: createDate(i, 8 + (j * 2), (j * 17) % 60),
        operator: 'Operator 2'
      });
    }
  }

  // Generate 60 inspections for older dates (up to 90 days ago)
  for (let i = 8; i <= 75; i += 3) {
    const isRejected = i % 4 === 0;
    const partNo = parts[i % parts.length];
    const shift = SHIFTS[i % 3];
    const defect = isRejected ? DEFECT_TYPES[i % DEFECT_TYPES.length] : null;
    const ssim = isRejected ? 0.62 + Math.random() * 0.2 : 0.93 + Math.random() * 0.06;

    inspectionsDB.push({
      id: `INS-${String(idCounter++).padStart(6, '0')}`,
      inspection_id: `INS-${String(idCounter).padStart(6, '0')}`,
      part_number: partNo,
      part_name: PART_NAMES[partNo],
      image_name: `IMG_${partNo}_HIST_${i}.jpg`,
      result: isRejected ? 'Rejected' : 'Accepted',
      ssim_score: parseFloat(ssim.toFixed(3)),
      defect_type: defect,
      best_match: `${partNo}_master.jpg`,
      location: LOCATIONS[i % LOCATIONS.length],
      shifts: shift,
      timestamp: createDate(i, 10, (i * 7) % 60),
      operator: 'Quality Inspector'
    });
  }
}

seedInspections();

// System State
let isInspectionRunning = false;
let isInspectionPaused = false;
let selectedPartNumber = '46152';
let camerasActive = false;
let lastLiveResult = {
  component: 'Valve Seat',
  ssim_score: 0.962,
  status: 'Accepted',
  image_name: 'Kappa1.2 L_Inlet.jpg',
  timestamp: new Date().toISOString()
};

// ================= PAGE ROUTES =================

app.get('/', (req, res) => {
  res.redirect('/home');
});

app.get('/login', (req, res) => {
  res.render('login.html');
});

app.post('/login', (req, res) => {
  const { username } = req.body;
  req.session.user = username || 'admin';
  req.session.role = 'ADMIN';
  req.session.location = 'Plant P2';
  res.redirect('/home');
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => {
    res.redirect('/login');
  });
});

app.get('/home', (req, res) => {
  res.render('home.html');
});

app.get('/index', (req, res) => {
  res.render('index.html');
});

app.get('/dashboard', (req, res) => {
  res.render('dashboard.html');
});

app.get('/defect_dashboard', (req, res) => {
  res.render('defect_dashboard.html');
});

app.get('/filter', (req, res) => {
  res.render('filter.html');
});

app.get('/training', (req, res) => {
  res.render('training.html');
});

app.get('/valve-specs', (req, res) => {
  res.render('valve_specs.html');
});

app.get('/control_panel', (req, res) => {
  res.render('control_panel.html');
});

app.get('/flow-editor', (req, res) => {
  res.render('flow_editor.html');
});

app.get('/overview', (req, res) => {
  res.render('overview.html');
});

app.get('/api/overview', (req, res) => {
  res.render('overview.html');
});

app.get('/profile', (req, res) => {
  res.render('profile.html', { user: req.session.user || 'admin' });
});

app.get('/report', (req, res) => {
  res.render('report.html');
});

app.get('/report/:id', (req, res) => {
  res.render('report.html', { report_id: req.params.id });
});

app.get('/inspection/:part_number', (req, res) => {
  const partNo = req.params.part_number;
  const recent = inspectionsDB.filter((i) => i.part_number === partNo).slice(0, 10);
  res.render('inspection_details.html', {
    inspection: recent[0] || null,
    inspections: recent,
    part_number: partNo
  });
});

app.get('/inspection', (req, res) => {
  res.render('inspection_details.html', {
    inspection: inspectionsDB[0] || null,
    inspections: inspectionsDB.slice(0, 10)
  });
});

// ================= API ENDPOINTS =================

// Helper to filter inspections by time range
function filterByTime(list: InspectionRecord[], timeFilter: string): InspectionRecord[] {
  const now = new Date();
  let cutoff = new Date();

  switch (timeFilter?.toLowerCase()) {
    case 'daily':
    case 'today':
      cutoff = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      break;
    case 'weekly':
      cutoff = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      break;
    case 'monthly':
      cutoff = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      break;
    case '3months':
      cutoff = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
      break;
    case '6months':
      cutoff = new Date(now.getTime() - 180 * 24 * 60 * 60 * 1000);
      break;
    case 'yearly':
      cutoff = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
      break;
    default:
      return list;
  }

  return list.filter((item) => new Date(item.timestamp) >= cutoff);
}

// 1. Dashboard Stats (Today and All-Time)
app.get('/dashboard_stats', (req, res) => {
  const todayRecords = filterByTime(inspectionsDB, 'daily');
  const acceptedToday = todayRecords.filter((r) => r.result === 'Accepted').length;
  const rejectedToday = todayRecords.filter((r) => r.result === 'Rejected').length;
  const uniquePartsToday = new Set(todayRecords.map((r) => r.part_number)).size;
  const passRateToday = todayRecords.length > 0 ? Math.round((acceptedToday / todayRecords.length) * 100) : 0;

  const acceptedTotal = inspectionsDB.filter((r) => r.result === 'Accepted').length;
  const rejectedTotal = inspectionsDB.filter((r) => r.result === 'Rejected').length;
  const uniquePartsTotal = new Set(inspectionsDB.map((r) => r.part_number)).size;
  const passRateTotal = inspectionsDB.length > 0 ? Math.round((acceptedTotal / inspectionsDB.length) * 100) : 0;

  res.json({
    inspected: todayRecords.length,
    pass_rate: passRateToday,
    rejected: rejectedToday,
    accepted: acceptedToday,
    parts: uniquePartsToday,

    inspected_total: inspectionsDB.length,
    pass_rate_total: passRateTotal,
    rejected_total: rejectedTotal,
    accepted_total: acceptedTotal,
    parts_total: uniquePartsTotal
  });
});

// 2. Chart Data Endpoint
app.get('/api/chart-data', (req, res) => {
  let { location, part_number, shift, time_filter } = req.query as Record<string, string>;

  let filtered = inspectionsDB;

  if (time_filter) {
    filtered = filterByTime(filtered, time_filter);
  }

  if (location && !['all', 'allplants'].includes(location.toLowerCase().replace(/\s+/g, ''))) {
    filtered = filtered.filter((r) => r.location.toLowerCase() === location.toLowerCase());
  }

  if (shift && !['all', 'allshifts'].includes(shift.toLowerCase().replace(/\s+/g, ''))) {
    filtered = filtered.filter((r) => r.shifts.toLowerCase() === shift.toLowerCase());
  }

  if (part_number && !['all', 'allparts', 'none', ''].includes(part_number.toLowerCase())) {
    filtered = filtered.filter((r) => r.part_number === part_number);
  }

  const accepted = filtered.filter((r) => r.result === 'Accepted').length;
  const rejected = filtered.filter((r) => r.result === 'Rejected').length;

  res.json({
    accepted,
    rejected,
    total: filtered.length
  });
});

// 3. Inspection Details drill-down table
app.get('/api/inspection-details', (req, res) => {
  const { status, location, part_number, shift, time_filter } = req.query as Record<string, string>;

  let filtered = inspectionsDB;

  if (time_filter) {
    filtered = filterByTime(filtered, time_filter);
  }

  if (status) {
    const targetStatus = status.toLowerCase() === 'accepted' ? 'Accepted' : 'Rejected';
    filtered = filtered.filter((r) => r.result === targetStatus);
  }

  if (location && !['all', 'allplants'].includes(location.toLowerCase().replace(/\s+/g, ''))) {
    filtered = filtered.filter((r) => r.location.toLowerCase() === location.toLowerCase());
  }

  if (shift && !['all', 'allshifts'].includes(shift.toLowerCase().replace(/\s+/g, ''))) {
    filtered = filtered.filter((r) => r.shifts.toLowerCase() === shift.toLowerCase());
  }

  if (part_number && !['all', 'allparts', 'none', ''].includes(part_number.toLowerCase())) {
    filtered = filtered.filter((r) => r.part_number === part_number);
  }

  const rows = filtered.map((r) => ({
    Part_number: r.part_number,
    Image_name: r.image_name,
    Result: r.result,
    ssim_score: r.ssim_score,
    Defect_type: r.defect_type,
    Best_match: r.best_match,
    Location: r.location,
    Shifts: r.shifts,
    Timestamp: r.timestamp
  }));

  res.json(rows);
});

// 4. Defect Dashboard Types Breakdown
app.get('/api/defect-dashboard/types', (req, res) => {
  const { part_number, time_filter } = req.query as Record<string, string>;

  let rejected = inspectionsDB.filter((r) => r.result === 'Rejected');

  if (time_filter && time_filter !== 'none') {
    rejected = filterByTime(rejected, time_filter);
  }

  if (part_number && !['all', 'none', ''].includes(part_number.toLowerCase())) {
    rejected = rejected.filter((r) => r.part_number === part_number);
  }

  const counts: Record<string, number> = {};
  DEFECT_TYPES.forEach((t) => (counts[t] = 0));

  rejected.forEach((r) => {
    if (r.defect_type) {
      counts[r.defect_type] = (counts[r.defect_type] || 0) + 1;
    }
  });

  const chart_labels = Object.keys(counts).filter((k) => counts[k] > 0);
  const chart_values = chart_labels.map((k) => counts[k]);
  const data = chart_labels.map((label, idx) => ({
    label,
    count: chart_values[idx]
  }));

  res.json({
    chart_labels,
    chart_values,
    data
  });
});

// 5. Shift Statistics
app.get('/api/shift-stats', (req, res) => {
  const todayRecords = filterByTime(inspectionsDB, 'daily');
  const shiftA = todayRecords.filter((r) => r.shifts === 'Shift A');
  const shiftB = todayRecords.filter((r) => r.shifts === 'Shift B');
  const shiftC = todayRecords.filter((r) => r.shifts === 'Shift C');

  res.json({
    data: [
      {
        shift: 'Shift A',
        accepted: shiftA.filter((r) => r.result === 'Accepted').length,
        rejected: shiftA.filter((r) => r.result === 'Rejected').length
      },
      {
        shift: 'Shift B',
        accepted: shiftB.filter((r) => r.result === 'Accepted').length,
        rejected: shiftB.filter((r) => r.result === 'Rejected').length
      },
      {
        shift: 'Shift C',
        accepted: shiftC.filter((r) => r.result === 'Accepted').length,
        rejected: shiftC.filter((r) => r.result === 'Rejected').length
      }
    ]
  });
});

// 6. Rejected Data Filter
app.get('/api/rejected-data/:filter_type', (req, res) => {
  const filterType = req.params.filter_type;
  const filtered = filterByTime(
    inspectionsDB.filter((r) => r.result === 'Rejected'),
    filterType
  );
  const rows = filtered.map((r) => ({
    Part_number: r.part_number,
    Result: r.result,
    Defect_type: r.defect_type,
    timestamp: r.timestamp
  }));
  res.json(rows);
});

// 7. Accepted Data Filter
app.get('/api/accepted-data/:filter_type', (req, res) => {
  const filterType = req.params.filter_type;
  const filtered = filterByTime(
    inspectionsDB.filter((r) => r.result === 'Accepted'),
    filterType
  );
  const rows = filtered.map((r) => ({
    Part_number: r.part_number,
    Result: r.result,
    Defect_type: r.defect_type || 'None',
    timestamp: r.timestamp
  }));
  res.json(rows);
});

// 8. Valve Specs API
app.get('/api/valve-specs', (req, res) => {
  const partNumber = req.query.part_number as string;
  if (!partNumber) {
    return res.status(400).send('Part number is required');
  }

  const specs = valveSpecsMap[partNumber];
  if (!specs) {
    return res.status(404).send(`No data found for Part Number ${partNumber}`);
  }

  res.json(specs);
});

// 9. Trained Parts
app.get('/api/trained-parts', (req, res) => {
  res.json(Object.keys(PART_NAMES));
});

// 10. Inspection Status
app.get('/api/inspection/status', (req, res) => {
  const todayRecords = filterByTime(inspectionsDB, 'daily');
  const passed = todayRecords.filter((r) => r.result === 'Accepted').length;
  const failed = todayRecords.filter((r) => r.result === 'Rejected').length;

  res.json({
    running: isInspectionRunning,
    paused: isInspectionPaused,
    total_inspections: todayRecords.length,
    passed,
    failed,
    selected_part_number: selectedPartNumber,
    current_part: PART_NAMES[selectedPartNumber] || 'Unknown',
    session: {
      is_running: isInspectionRunning,
      current_part: selectedPartNumber
    }
  });
});

app.post('/api/inspection/start', (req, res) => {
  isInspectionRunning = true;
  isInspectionPaused = false;
  if (req.body?.part_number) {
    selectedPartNumber = req.body.part_number;
  }
  res.json({ status: 'success', message: 'Inspection started' });
});

app.post('/api/inspection/stop', (req, res) => {
  isInspectionRunning = false;
  isInspectionPaused = false;
  res.json({ status: 'success', message: 'Inspection stopped' });
});

app.post('/api/inspection/pause', (req, res) => {
  isInspectionPaused = true;
  res.json({ status: 'success', message: 'Inspection paused' });
});

app.post('/api/inspection/resume', (req, res) => {
  isInspectionPaused = false;
  res.json({ status: 'success', message: 'Inspection resumed' });
});

app.get('/api/inspection/active-part', (req, res) => {
  res.json({ part_number: selectedPartNumber });
});

app.post('/api/inspection/active-part', (req, res) => {
  if (req.body?.part_number) {
    selectedPartNumber = req.body.part_number;
  }
  res.json({ status: 'success', part_number: selectedPartNumber });
});

// 11. Valve Types Configuration
app.get('/api/valve_types', (req, res) => {
  res.json({
    status: 'success',
    valve_types: {
      'Gate Valve': {
        required_images: 7,
        positions: ['Front', 'Back', 'Left', 'Right', 'Top', 'Bottom', 'Marking']
      },
      'Ball Valve': {
        required_images: 5,
        positions: ['Front', 'Back', 'Side', 'Top', 'Bottom']
      },
      'Check Valve': {
        required_images: 6,
        positions: ['Front', 'Back', 'Top', 'Bottom', 'Inlet', 'Outlet']
      },
      'Butterfly Valve': {
        required_images: 8,
        positions: ['Front', 'Back', 'Left', 'Right', 'Top', 'Bottom', 'Flange_A', 'Flange_B']
      },
      'Globe Valve': {
        required_images: 10,
        positions: ['Front', 'Back', 'Left', 'Right', 'Top', 'Bottom', 'Seat', 'Stem', 'Handwheel', 'Marking']
      }
    }
  });
});

app.post('/api/inspection/start_session', (req, res) => {
  res.json({
    status: 'success',
    session: {
      inspection_id: `INS-${Date.now()}`,
      valve_type: req.body?.valve_type || 'Gate Valve',
      required_images: 7,
      status: 'INSPECTION_STARTED'
    }
  });
});

app.post('/api/inspection/capture_view', (req, res) => {
  res.json({
    status: 'success',
    message: 'View captured',
    captured_images: 1
  });
});

app.get('/api/inspection/current_status', (req, res) => {
  res.json({
    status: 'success',
    current_status: 'IN_PROGRESS'
  });
});

app.post('/api/inspection/complete', (req, res) => {
  res.json({
    status: 'success',
    result: 'Accepted'
  });
});

// 12. Camera Management Endpoints
app.post('/start_camera', (req, res) => {
  camerasActive = true;
  res.json({
    status: 'started',
    cameras: ['cam1', 'cam2', 'cam3'],
    failed: {},
    diagnostics: {
      available_cameras: 3,
      started_cameras: 3,
      failed_cameras: 0
    }
  });
});

app.post('/stop_camera', (req, res) => {
  camerasActive = false;
  res.json({ status: 'stopped' });
});

app.get('/check_cameras', (req, res) => {
  res.json({
    available_cameras: 3,
    status: {
      cam1: 'Ready',
      cam2: 'Ready',
      cam3: 'Ready'
    },
    message: 'Found 3 USB/GigE cameras available'
  });
});

// Video Feed (serves SVG simulation frame or sample image)
app.get('/video_feed/:cam_id', (req, res) => {
  const camId = req.params.cam_id;

  // We can return a high quality SVG stream / image with camera telemetry
  const timeStr = new Date().toLocaleTimeString();
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
    <rect width="640" height="480" fill="#0d1117" />
    <defs>
      <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#1f2937" />
        <stop offset="100%" stop-color="#111827" />
      </linearGradient>
    </defs>
    <rect x="20" y="20" width="600" height="440" rx="10" fill="url(#g)" stroke="#374151" stroke-width="2" />
    <!-- Crosshairs & Grid -->
    <line x1="320" y1="40" x2="320" y2="440" stroke="#3b82f6" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>
    <line x1="40" y1="240" x2="600" y2="240" stroke="#3b82f6" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>
    <circle cx="320" cy="240" r="80" fill="none" stroke="#06b6d4" stroke-width="1.5" stroke-dasharray="6 3" />
    <circle cx="320" cy="240" r="140" fill="none" stroke="#06b6d4" stroke-width="1" opacity="0.4" />
    
    <!-- Valve Silhouette -->
    <path d="M 280 140 L 360 140 L 330 200 L 330 340 L 350 360 L 290 360 L 310 340 L 310 200 Z" fill="#4b5563" stroke="#9ca3af" stroke-width="2"/>
    <circle cx="320" cy="140" r="28" fill="#374151" stroke="#60a5fa" stroke-width="2"/>
    
    <!-- Status Overlays -->
    <text x="40" y="60" fill="#10b981" font-family="monospace" font-size="16" font-weight="bold">● LIVE [${camId.toUpperCase()}]</text>
    <text x="40" y="85" fill="#9ca3af" font-family="monospace" font-size="13">FPS: 30.0 | RES: 1920x1080</text>
    <text x="40" y="110" fill="#9ca3af" font-family="monospace" font-size="13">PART: ${selectedPartNumber} (${PART_NAMES[selectedPartNumber] || 'Unknown'})</text>
    
    <text x="440" y="60" fill="#60a5fa" font-family="monospace" font-size="14">${timeStr}</text>
    <text x="440" y="85" fill="#10b981" font-family="monospace" font-size="14">STATUS: NORMAL</text>
    
    <rect x="230" y="400" width="180" height="30" rx="5" fill="#111827" stroke="#10b981" stroke-width="1"/>
    <text x="250" y="421" fill="#10b981" font-family="sans-serif" font-size="14" font-weight="bold">PASS (SSIM: 0.96)</text>
  </svg>`;

  res.setHeader('Content-Type', 'image/svg+xml');
  res.setHeader('Cache-Control', 'no-cache');
  res.send(svg);
});

// Capture Frame Endpoint (Simulates Inspection Run)
app.post('/capture_frame', (req, res) => {
  const partNumber = req.body?.part_number || selectedPartNumber;
  const isPass = Math.random() > 0.15; // 85% pass rate
  const ssim = isPass ? 0.93 + Math.random() * 0.06 : 0.68 + Math.random() * 0.14;
  const defect = isPass ? null : DEFECT_TYPES[Math.floor(Math.random() * DEFECT_TYPES.length)];

  const now = new Date();
  const newRecord: InspectionRecord = {
    id: `INS-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(inspectionsDB.length + 1).padStart(4, '0')}`,
    inspection_id: `INS-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(inspectionsDB.length + 1).padStart(4, '0')}`,
    part_number: partNumber,
    part_name: PART_NAMES[partNumber] || 'Valve Part',
    image_name: `IMG_${partNumber}_${Date.now()}.jpg`,
    result: isPass ? 'Accepted' : 'Rejected',
    ssim_score: parseFloat(ssim.toFixed(3)),
    defect_type: defect,
    best_match: `${partNumber}_master.jpg`,
    location: req.session.location || 'Plant P2',
    shifts: now.getHours() >= 6 && now.getHours() < 14 ? 'Shift A' : now.getHours() >= 14 && now.getHours() < 22 ? 'Shift B' : 'Shift C',
    timestamp: now.toISOString(),
    operator: req.session.user || 'Operator'
  };

  inspectionsDB.unshift(newRecord);

  lastLiveResult = {
    component: PART_NAMES[partNumber] || 'Valve Component',
    ssim_score: newRecord.ssim_score,
    status: newRecord.result,
    image_name: newRecord.image_name,
    timestamp: newRecord.timestamp
  };

  res.json({
    status: 'success',
    result: newRecord.result,
    defect_type: newRecord.defect_type,
    ssim_score: newRecord.ssim_score,
    best_match: newRecord.best_match,
    part_number: partNumber,
    part_name: newRecord.part_name,
    image_path: `/static/Golden Libraries/GoldenLibrary/${partNumber}/Kappa1.2 L_Inlet.jpg`,
    results: [
      {
        cam: 'cam1',
        result: newRecord.result,
        ssim: newRecord.ssim_score,
        image: `/static/Golden Libraries/GoldenLibrary/${partNumber}/Kappa1.2 L_Inlet.jpg`
      }
    ]
  });
});

app.get('/api/latest-live', (req, res) => {
  res.json(lastLiveResult);
});

app.get('/api/daily-notification', (req, res) => {
  res.json({
    message: 'System nominal. 4 defects detected in Shift A.',
    timestamp: new Date().toISOString()
  });
});

// CSV Export Downloads
const handleCsvDownload = (req: express.Request, res: express.Response, filename: string) => {
  const headers = ['Inspection_ID', 'Part_Number', 'Part_Name', 'Location', 'Shifts', 'Result', 'Defect_Type', 'SSIM_Score', 'Timestamp', 'Operator'];
  const rows = inspectionsDB.map((r) =>
    [
      r.inspection_id,
      r.part_number,
      `"${r.part_name}"`,
      r.location,
      r.shifts,
      r.result,
      `"${r.defect_type || 'None'}"`,
      r.ssim_score,
      r.timestamp,
      r.operator
    ].join(',')
  );

  const csv = [headers.join(','), ...rows].join('\n');
  res.setHeader('Content-Type', 'text/csv');
  res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
  res.send(csv);
};

app.get('/download_daily_report', (req, res) => handleCsvDownload(req, res, 'Daily_Inspection_Report.csv'));
app.get('/download_excel', (req, res) => handleCsvDownload(req, res, 'Inspection_Report.csv'));
app.get('/api/reports/filter-export', (req, res) => handleCsvDownload(req, res, 'Filtered_Inspection_Report.csv'));
app.get('/api/reports/daily', (req, res) => handleCsvDownload(req, res, 'Daily_Report.csv'));
app.get('/api/reports/range', (req, res) => handleCsvDownload(req, res, 'Range_Report.csv'));
app.get('/api/reports/dashboard-download', (req, res) => handleCsvDownload(req, res, 'Dashboard_Report.csv'));
app.get('/api/report/download', (req, res) => handleCsvDownload(req, res, 'Report_Download.csv'));

// Additional stubs for UI controls
app.post('/api/toggle_software', (req, res) => res.json({ status: 'toggled' }));
app.post('/api/trigger_camera', (req, res) => res.json({ status: 'triggered' }));
app.post('/set_exposure', (req, res) => res.json({ status: 'exposure_set' }));
app.post('/set_gain', (req, res) => res.json({ status: 'gain_set' }));
app.post('/set_trigger', (req, res) => res.json({ status: 'trigger_set' }));
app.post('/software_trigger', (req, res) => res.json({ status: 'software_trigger_fired' }));
app.post('/camera/config', (req, res) => res.json({ status: 'config_saved' }));
app.post('/api/workflow/run', (req, res) => res.json({ status: 'success', message: 'Workflow executed successfully' }));
app.post('/api/train-edges', (req, res) => res.json({ status: 'trained', message: 'Edges trained successfully' }));
app.get('/api/view-edges/:part_number', (req, res) => res.json({ status: 'edges_found', edges: [] }));
app.get('/api/diagnostics', (req, res) => res.json({ cameras: 'OK', database: 'IN_MEMORY', status: 'HEALTHY' }));
app.post('/api/reset-stats', (req, res) => res.json({ status: 'reset_ok' }));

// Start server
app.listen(PORT, HOST, () => {
  console.log(`[Valve Inspection] Server running on http://${HOST}:${PORT}`);
});
