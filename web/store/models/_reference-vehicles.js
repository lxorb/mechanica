const license = {author: 'VTX', license: 'CC BY-NC-SA 4.0', licenseUrl: 'https://creativecommons.org/licenses/by-nc-sa/4.0/'};

export const VEHICLES = {
  'yzf-2021': {
    id: 'yzf-2021', brand: 'Yamaha', name: 'YZF', edition: '2021 source model', type: 'motorcycle',
    source: {...license, title: 'Yamaha YZF 2021', url: 'https://sketchfab.com/3d-models/yamaha-yzf-2021-0af46985abc54219be3aaf0991f5a3de'},
    coverage: 'Exterior engine geometry and separate visual assemblies. No verified fuse, wiring, pistons or gearbox internals. Source naming suggests R7; model year and dimensions are unverified.',
    repairId: 'r7-main-fuse', region: 'bodywork', engineGroup: 'engine-exterior', transfer: '8.0 MB', original: '29.8 MB',
  },
  'honda-cbr650r': {
    id: 'honda-cbr650r', brand: 'Honda', name: 'CBR650R', edition: 'Source model · year unverified', type: 'motorcycle',
    source: {...license, title: 'Honda CBR650R', url: 'https://sketchfab.com/3d-models/honda-cbr650r-b9ec190f902d4180aa527659af3f5089'},
    coverage: 'Engine assembly contains 11 original meshes that can be separated for inspection. These are artist mesh divisions, not 11 identified service parts. Pistons, valves, crankshaft and the main fuse are not verified as separate components.',
    repairId: 'cbr650r-main-fuse', region: 'bodywork', engineGroup: 'engine-exterior', transfer: '7.8 MB', original: '30.0 MB',
  },
  'corvette-c8': {
    id: 'corvette-c8', brand: 'Chevrolet', name: 'Corvette C8', edition: 'Stingray · source titled 2019', type: 'car',
    source: {author: 'Hari', title: '2019 Chevrolet Corvette C8 Stingray', url: 'https://sketchfab.com/3d-models/2019-chevrolet-corvette-c8-stingray-790c40ccff6843eab0b7b4bd18421ff8', license: 'CC BY 4.0', licenseUrl: 'https://creativecommons.org/licenses/by/4.0/'},
    coverage: 'Engine and bay contain 3 original meshes, plus a separate engine-bay bolt group. The cover and pipes can be separated as authored; pistons, valves, crankshaft and a service-ready engine teardown are not verified. The artist title says 2019; C8 manual reference is model year 2020.',
    repairId: 'c8-air-filter', region: 'engine-bay', engineGroup: 'engine-bay', transfer: '6.1 MB', original: '13.5 MB',
  },
};

export const vehicleUrl = id => `/vehicles/${id}`;
export const VEHICLE_REDIRECTS = {'bmw-s1000rr': 'honda-cbr650r', 'fenomeno-2026': 'corvette-c8'};
