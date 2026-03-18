# OpenReel Deployment Guide

## Deploying to Cloudflare Pages

OpenReel is configured to deploy to Cloudflare Pages at `app.openreel.video`.

### Prerequisites

1. **Cloudflare Account**: You need a Cloudflare account with access to the `openreel.video` domain
2. **Wrangler CLI**: Install wrangler globally or use the local version
   ```bash
   pnpm install
   ```

### Initial Setup

1. **Login to Cloudflare**:
   ```bash
   cd apps/web
   npx wrangler login
   ```

2. **Create Cloudflare Pages Project** (first time only):
   ```bash
   npx wrangler pages project create openreel
   ```

3. **Configure Custom Domain** (in Cloudflare Dashboard):
   - Go to Cloudflare Pages → openreel project → Custom domains
   - Add `app.openreel.video` as a custom domain
   - Cloudflare will automatically configure the DNS

### Deployment Commands

#### Production Deployment

Deploy to production (app.openreel.video):

```bash
# From project root
pnpm deploy

# Or from apps/web directory
pnpm build
pnpm deploy
```

#### Preview Deployment

Deploy a preview version for testing:

```bash
# From project root
pnpm deploy:preview

# Or from apps/web directory
pnpm build
pnpm deploy:preview
```

### Important Configuration

#### Required Headers

The app requires special headers for SharedArrayBuffer (used by FFmpeg.wasm):
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Embedder-Policy: require-corp`

These are configured in `apps/web/public/_headers` and will be automatically deployed.

#### SPA Routing

The `apps/web/public/_redirects` file ensures all routes are handled by the React app:
```
/* /index.html 200
```

### Build Configuration

- **Build Command**: `tsc --noEmit && vite build`
- **Build Output**: `dist/`
- **Node Version**: >= 18.0.0

### Verifying Deployment

After deployment, verify:

1. **Access the site**: https://app.openreel.video
2. **Check headers**: Open DevTools → Network tab → Check response headers for COOP/COEP
3. **Test video export**: Try exporting a video to ensure WebCodecs and FFmpeg.wasm work

### Troubleshooting

#### SharedArrayBuffer Not Available

If you see errors about SharedArrayBuffer:
- Check that the COOP/COEP headers are present in Network tab
- Verify `_headers` file was deployed to Cloudflare Pages
- Clear browser cache and hard reload

#### 404 on Routes

If direct URL access shows 404:
- Verify `_redirects` file is in the `dist/` folder after build
- Check Cloudflare Pages → Functions → Redirects

#### Deployment Fails

```bash
# Check wrangler authentication
npx wrangler whoami

# Re-login if needed
npx wrangler logout
npx wrangler login
```

### CI/CD Integration

For automated deployments, use GitHub Actions:

```yaml
name: Deploy to Cloudflare Pages

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v2
      - uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'pnpm'

      - run: pnpm install
      - run: pnpm build

      - name: Deploy to Cloudflare Pages
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy dist --project-name=openreel
          workingDirectory: apps/web
```

### Environment Variables

If you need environment variables in production:

1. Go to Cloudflare Pages → openreel → Settings → Environment variables
2. Add variables (they'll be available at build time)
3. Redeploy for changes to take effect

### Monitoring

- **Analytics**: Available in Cloudflare Pages dashboard
- **Logs**: Check Cloudflare Pages → openreel → Deployments → View logs
- **Performance**: Use Web Analytics in Cloudflare dashboard
