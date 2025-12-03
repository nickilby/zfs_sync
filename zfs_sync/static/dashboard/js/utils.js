function formatDate(dateString) {
    if (!dateString) return 'N/A';
    try {
        const date = new Date(dateString);
        return date.toLocaleString();
    } catch (e) {
        return dateString;
    }
}

function formatNumber(num) {
    if (typeof num !== 'number') return 'N/A';
    return num.toLocaleString();
}
