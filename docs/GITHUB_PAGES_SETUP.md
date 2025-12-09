# GitHub Pages Setup Instructions

This document provides instructions for configuring GitHub Pages for the ZFS Sync documentation.

## Quick Setup

1. **Go to Repository Settings**
   - Navigate to your GitHub repository
   - Click on **Settings** (in the repository navigation bar)

2. **Configure Pages**
   - Scroll down to **Pages** in the left sidebar
   - Under **Source**, select:
     - **Branch**: `main` (or `master` if that's your default branch)
     - **Folder**: `/docs`
   - Click **Save**

3. **Wait for Deployment**
   - GitHub will build and deploy your documentation
   - This usually takes 1-2 minutes
   - You'll see a green checkmark when deployment is complete

4. **Access Your Documentation**
   - Your documentation will be available at:
     - `https://your-username.github.io/zfs_sync/`
     - Or `https://your-org.github.io/zfs_sync/` if in an organization

## Custom Domain (Optional)

If you want to use a custom domain:

1. **Add CNAME file** in the `docs/` folder:
   ```
   docs.example.com
   ```

2. **Configure DNS**:
   - Add a CNAME record pointing to `your-username.github.io`
   - Or add A records for GitHub Pages IPs

3. **Update GitHub Pages settings**:
   - Go to Settings > Pages
   - Enter your custom domain
   - Enable "Enforce HTTPS" (after DNS propagates)

## Verification

After setup, verify:

1. **Documentation loads**: Visit `https://your-username.github.io/zfs_sync/`
2. **Links work**: Click through to different documentation pages
3. **Navigation works**: Test the documentation structure
4. **Mobile friendly**: Check on mobile device

## Troubleshooting

### Documentation Not Appearing

- **Check build status**: Go to Actions tab, look for "pages build and deployment"
- **Check branch**: Ensure you selected the correct branch
- **Check folder**: Ensure `/docs` folder is selected
- **Wait longer**: First deployment can take up to 10 minutes

### Links Not Working

- **Check link format**: Links should be relative (e.g., `[Guide](GUIDE.md)`)
- **Check file names**: Ensure file names match exactly (case-sensitive)
- **Check Jekyll**: GitHub Pages uses Jekyll - some markdown features may need adjustment

### Build Errors

- **Check `_config.yml`**: Ensure it's valid YAML
- **Check excluded files**: Files in `exclude` list won't be processed
- **Check Jekyll plugins**: Only whitelisted plugins work on GitHub Pages

## Updating Documentation

Documentation updates automatically when you:

1. Push changes to the `main` branch
2. Files are in the `/docs` folder
3. GitHub Pages is enabled

No manual deployment needed - just push and wait 1-2 minutes.

## Advanced Configuration

### Jekyll Theme

The `_config.yml` file uses the `minima` theme. You can:

- Change theme in `_config.yml`
- Customize theme with `_sass/` directory
- Use a different Jekyll theme

### Custom 404 Page

Create `docs/404.md` for a custom 404 page.

### Search Functionality

For search functionality, consider:
- Using Jekyll plugins (if whitelisted)
- Adding client-side search with JavaScript
- Using external search service

## Notes

- GitHub Pages is free for public repositories
- Private repositories can use GitHub Pages with GitHub Pro/Team
- Documentation is automatically versioned with your repository
- HTTPS is enabled by default
- Custom domains can be configured

## Resources

- [GitHub Pages Documentation](https://docs.github.com/en/pages)
- [Jekyll Documentation](https://jekyllrb.com/docs/)
- [GitHub Pages Themes](https://pages.github.com/themes/)
