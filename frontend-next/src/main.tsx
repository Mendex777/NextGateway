import { createRoot } from 'react-dom/client';
import { message } from 'antd';
import 'antd/dist/reset.css';
import '@/styles/utils.css';
import '@/styles/page-shell.css';
import '@/styles/page-cards.css';

import { readyI18n } from '@/i18n/react';
import NextGatewayApp from '@/nextgateway/App';

const messageContainer = document.getElementById('message');
if (messageContainer) {
  message.config({ getContainer: () => messageContainer });
}

readyI18n().then(() => {
  const root = document.getElementById('app');
  if (root) {
    createRoot(root).render(
      <NextGatewayApp />,
    );
  }
});
