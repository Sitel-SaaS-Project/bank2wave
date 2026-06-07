import React, { useEffect, useState, useCallback } from 'react';
import api from '../api/client.ts';
import { useNavigate } from 'react-router-dom';

declare global {
  interface Window {
    Plaid: any;
  }
}

interface SyncLog {
  id: number;
  bank_account_id: number;
  status: string;
  transactions_synced: number;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

interface BankAccount {
  id: number;
  connector_id: string;
  account_label: string | null;
  wave_account_name: string;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
}

const Dashboard: React.FC = () => {
  const [user, setUser] = useState<any>(null);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [logs, setLogs] = useState<SyncLog[]>([]);
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [linking, setLinking] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [userRes, accountsRes, logsRes, planRes] = await Promise.all([
          api.get('/auth/me'),
          api.get('/sync/accounts'),
          api.get('/sync/history'),
          api.get('/billing/my-plan'),
        ]);
        setUser(userRes.data);
        setAccounts(accountsRes.data);
        setLogs(logsRes.data);
        setPlan(planRes.data);
      } catch (err) {
        navigate('/login');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [navigate]);

  const handleConnectBank = useCallback(async () => {
    setLinking(true);
    try {
      const res = await api.get('/sync/plaid-link-token/bmo');
      const linkToken = res.data.link_token;
      const handler = window.Plaid.create({
        token: linkToken,
        onSuccess: async (public_token: string, metadata: any) => {
          const account_id = metadata.accounts[0]?.id || '';
          await api.post('/sync/link-account', {
            connector_id: metadata.institution?.name || 'bank',
            plaid_public_token: public_token,
            plaid_account_id: account_id,
            account_label: metadata.institution?.name || 'My Bank',
            wave_account_name: 'Bank',
          });
          const accountsRes = await api.get('/sync/accounts');
          setAccounts(accountsRes.data);
        },
        onExit: () => setLinking(false),
      });
      handler.open();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to connect bank');
      setLinking(false);
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('plan');
    navigate('/login');
  };

  const handleRemoveAccount = async (id: number) => {
    await api.delete(`/sync/accounts/${id}`);
    setAccounts(accounts.filter(a => a.id !== id));
  };

  const handleSync = async (id: number) => {
    try {
      const res = await api.post(`/sync/run/${id}`);
      setLogs([res.data, ...logs]);
      const accountsRes = await api.get('/sync/accounts');
      setAccounts(accountsRes.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Sync failed');
    }
  };

  if (loading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="text-white text-xl">Loading...</div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex justify-between items-center">
        <h1 className="text-xl font-bold text-blue-400">bank2wave</h1>
        <div className="flex items-center gap-4">
          <span className="text-gray-400 text-sm">{user?.email}</span>
          <span className="bg-blue-600 text-white text-xs px-3 py-1 rounded-full uppercase">{plan?.current_plan}</span>
          <button onClick={handleLogout} className="text-gray-400 hover:text-white text-sm transition">Logout</button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-8">

        <div className="bg-gray-900 rounded-2xl p-6 flex justify-between items-center">
          <div>
            <p className="text-gray-400 text-sm">Current Plan</p>
            <p className="text-2xl font-bold capitalize">{plan?.current_plan} — ${plan?.price_monthly}/mo</p>
            <p className="text-gray-400 text-sm mt-1">Sync: {plan?.sync_frequency} · Max accounts: {plan?.max_accounts}</p>
          </div>
          <button className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg font-semibold transition">
            Upgrade Plan
          </button>
        </div>

        <div className="bg-gray-900 rounded-2xl p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Bank Accounts</h2>
            <div className="flex items-center gap-3">
              <span className="text-gray-400 text-sm">{accounts.length} / {plan?.max_accounts} connected</span>
              <button onClick={handleConnectBank} disabled={linking}
                className="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50">
                {linking ? 'Connecting...' : '+ Connect Bank'}
              </button>
            </div>
          </div>
          {accounts.length === 0 ? (
            <p className="text-gray-500 text-sm">No bank accounts connected yet. Click "Connect Bank" to get started!</p>
          ) : (
            <div className="space-y-3">
              {accounts.map(account => (
                <div key={account.id} className="bg-gray-800 rounded-xl p-4 flex justify-between items-center">
                  <div>
                    <p className="font-semibold">{account.account_label || account.connector_id}</p>
                    <p className="text-gray-400 text-sm">Wave: {account.wave_account_name}</p>
                    <p className="text-gray-500 text-xs mt-1">
                      Last synced: {account.last_synced_at ? new Date(account.last_synced_at).toLocaleString() : 'Never'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleSync(account.id)}
                      className="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-2 rounded-lg transition">
                      Sync Now
                    </button>
                    <button onClick={() => handleRemoveAccount(account.id)}
                      className="bg-red-600/20 hover:bg-red-600/40 text-red-400 text-sm px-4 py-2 rounded-lg transition">
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-gray-900 rounded-2xl p-6">
          <h2 className="text-lg font-semibold mb-4">Sync History</h2>
          {logs.length === 0 ? (
            <p className="text-gray-500 text-sm">No syncs yet.</p>
          ) : (
            <div className="space-y-2">
              {logs.map(log => (
                <div key={log.id} className="bg-gray-800 rounded-xl p-4 flex justify-between items-center">
                  <div>
                    <p className="text-sm font-semibold">Account #{log.bank_account_id}</p>
                    <p className="text-gray-400 text-xs">{new Date(log.started_at).toLocaleString()}</p>
                    {log.error_message && <p className="text-red-400 text-xs mt-1">{log.error_message}</p>}
                  </div>
                  <div className="text-right">
                    <span className={`text-xs px-3 py-1 rounded-full font-semibold ${
                      log.status === 'success' ? 'bg-green-500/20 text-green-400' :
                      log.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      'bg-yellow-500/20 text-yellow-400'
                    }`}>{log.status}</span>
                    <p className="text-gray-400 text-xs mt-1">{log.transactions_synced} transactions</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
};

export default Dashboard;
