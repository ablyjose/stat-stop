import axios from 'axios';

const api = axios.create({
    baseURL: 'http://localhost:8000',
    timeout: 240000, // 4 minutes to account for non-cached data
});

export const getEvents = async (year = 2025) => {
    const response = await api.get(`/events?year=${year}`);
    return response.data;
};

export const getStandings = async (year = 2025) => {
    const response = await api.get(`/standings?year=${year}`);
    return response.data;
};

export const getRacePace = async (year, gp, session, drivers) => {
    const response = await api.get('/race-pace', {
        params: { year, gp, session, drivers }
    });
    return response.data;
};

export const getTelemetry = async (year, gp, session, driver1, driver2) => {
    const response = await api.get('/telemetry', {
        params: { year, gp, session, driver1, driver2 }
    });
    return response.data;
};

export default api;
