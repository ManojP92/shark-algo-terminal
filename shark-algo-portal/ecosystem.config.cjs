module.exports = {
  apps: [
    {
      name: 'shark-node-bridge',
      cwd: './backend-node',
      script: 'server.mjs',
      interpreter: 'node',
      env: {
        NODE_ENV: 'production',
        PORT: 3001,
      },
      restart_delay: 3000,
      autorestart: true,
    },
    {
      name: 'shark-python-api',
      cwd: './backend-python',
      script: 'python3',
      args: '-m uvicorn api_server:app --host 0.0.0.0 --port 5001',
      restart_delay: 3000,
      autorestart: true,
    },
    {
      name: 'shark-frontend-ui',
      cwd: './frontend',
      script: 'npx',
      args: 'vite preview --host 0.0.0.0 --port 5000',
      restart_delay: 3000,
      autorestart: true,
    },
  ],
};
