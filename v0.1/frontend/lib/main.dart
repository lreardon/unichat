import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

void main() {
  runApp(const UnichatApp());
}

const _apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://127.0.0.1:8000');

class UnichatApp extends StatelessWidget {
  const UnichatApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Unichat MVP',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      home: const QueryPage(),
    );
  }
}

class QueryPage extends StatefulWidget {
  const QueryPage({super.key});

  @override
  State<QueryPage> createState() => _QueryPageState();
}

class _QueryPageState extends State<QueryPage> {
  final _questionController = TextEditingController();
  static final RegExp _sourceTagRe = RegExp(r'\[source\s+(\d+)\](?:\(([^)]+)\))?', caseSensitive: false);

  bool _loading = false;
  bool _loadingDomains = true;
  String? _selectedDomain;
  String? _domainLoadError;
  List<String> _domains = [];
  String _answer = '';
  List<dynamic> _citations = [];
  List<Map<String, dynamic>> _retrievedDocuments = [];
  String _originalQuestion = '';
  String _upgradedQuery = '';
  String _queryUpgradePrompt = '';
  String _systemPrompt = '';

  @override
  void initState() {
    super.initState();
    _loadDomains();
  }

  Future<void> refreshDomains() => _loadDomains();

  Future<void> _loadDomains() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/domains'));
      if (!mounted) return;

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final rawDomains = data['domains'] as List<dynamic>? ?? <dynamic>[];
        final domains = rawDomains.map((value) => value.toString()).toList();
        final selected = _selectedDomain;
        setState(() {
          _domains = domains;
          _selectedDomain = (selected != null && domains.contains(selected)) ? selected : null;
          _domainLoadError = null;
          _loadingDomains = false;
        });
      } else {
        setState(() {
          _domainLoadError = 'Failed to load domains (${response.statusCode}).';
          _loadingDomains = false;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _domainLoadError = 'Failed to load domains: $e';
        _loadingDomains = false;
      });
    }
  }

  Future<void> _submit() async {
    final question = _questionController.text.trim();
    if (question.isEmpty) return;
    if (_selectedDomain == null) return;

    final domains = <String>[_selectedDomain!];

    setState(() {
      _loading = true;
      _answer = '';
      _citations = [];
      _retrievedDocuments = [];
      _originalQuestion = '';
      _upgradedQuery = '';
      _queryUpgradePrompt = '';
      _systemPrompt = '';
    });

    try {
      final client = http.Client();
      try {
        final request = http.Request('POST', Uri.parse('$_apiBase/query/stream'));
        request.headers['content-type'] = 'application/json';
        request.body = jsonEncode({'question': question, 'domains': domains});

        final response = await client.send(request);

        if (response.statusCode < 200 || response.statusCode >= 300) {
          final errorBody = await response.stream.bytesToString();
          if (!mounted) return;
          setState(() {
            _answer = 'Request failed (${response.statusCode}): $errorBody';
          });
          return;
        }

        await for (final line in response.stream.transform(utf8.decoder).transform(const LineSplitter())) {
          final trimmed = line.trim();
          if (trimmed.isEmpty) continue;

          Map<String, dynamic> event;
          try {
            event = jsonDecode(trimmed) as Map<String, dynamic>;
          } catch (_) {
            continue;
          }

          final type = (event['type'] ?? '').toString();
          if (!mounted) return;

          if (type == 'query_upgrade') {
            setState(() {
              _originalQuestion = (event['original_question'] ?? question).toString();
              _upgradedQuery = (event['upgraded_question'] ?? '').toString();
              _queryUpgradePrompt = (event['system_prompt'] ?? '').toString();
            });
            continue;
          }

          if (type == 'retrieval') {
            final docs = (event['documents'] as List<dynamic>? ?? <dynamic>[]).whereType<Map<String, dynamic>>().toList();
            setState(() {
              _retrievedDocuments = docs;
            });
            continue;
          }

          if (type == 'prompt') {
            setState(() {
              _systemPrompt = (event['system_prompt'] ?? '').toString();
            });
            continue;
          }

          if (type == 'delta') {
            final delta = (event['delta'] ?? '').toString();
            if (delta.isEmpty) continue;
            setState(() {
              _answer += delta;
            });
            continue;
          }

          if (type == 'final') {
            setState(() {
              _answer = (event['answer'] ?? _answer).toString();
              _citations = (event['citations'] as List<dynamic>? ?? <dynamic>[]);
            });
          }
        }
      } finally {
        client.close();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _answer = 'Error: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _openUrl(String rawUrl) async {
    final uri = Uri.tryParse(rawUrl);
    if (uri == null) return;
    await launchUrl(uri, mode: LaunchMode.platformDefault);
  }

  Map<int, String> _citationUrlBySource() {
    final urls = <int, String>{};
    for (final citation in _citations) {
      final sourceRaw = citation['source'];
      final source = sourceRaw is int ? sourceRaw : int.tryParse(sourceRaw?.toString() ?? '');
      final url = (citation['url'] ?? '').toString();
      if (source != null && url.isNotEmpty) {
        urls[source] = url;
      }
    }
    return urls;
  }

  Widget _buildAnswerWithLinks(BuildContext context) {
    if (_answer.isEmpty) {
      return Text(_loading ? 'Generating response...' : 'No response yet.');
    }

    final sourceUrls = _citationUrlBySource();
    final spans = <InlineSpan>[];
    final defaultStyle = DefaultTextStyle.of(context).style;
    final linkStyle = TextStyle(
      color: Theme.of(context).colorScheme.primary,
      decoration: TextDecoration.underline,
    );

    var cursor = 0;
    for (final match in _sourceTagRe.allMatches(_answer)) {
      if (match.start > cursor) {
        spans.add(TextSpan(text: _answer.substring(cursor, match.start), style: defaultStyle));
      }

      final source = int.tryParse(match.group(1) ?? '');
      final inlineUrl = (match.group(2) ?? '').trim();
      final mappedUrl = source == null ? '' : (sourceUrls[source] ?? '');
      final url = inlineUrl.isNotEmpty ? inlineUrl : mappedUrl;
      final label = source == null ? match.group(0)! : '[source $source]';

      if (url.isNotEmpty) {
        spans.add(
          WidgetSpan(
            alignment: PlaceholderAlignment.baseline,
            baseline: TextBaseline.alphabetic,
            child: GestureDetector(
              onTap: () => _openUrl(url),
              child: Text(label, style: linkStyle),
            ),
          ),
        );
      } else {
        spans.add(TextSpan(text: match.group(0), style: defaultStyle));
      }

      cursor = match.end;
    }

    if (cursor < _answer.length) {
      spans.add(TextSpan(text: _answer.substring(cursor), style: defaultStyle));
    }

    return Text.rich(TextSpan(children: spans));
  }

  Future<void> _openAdminPage() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => AdminPage(onIngested: refreshDomains),
      ),
    );
  }

  @override
  void dispose() {
    _questionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Unichat RAG MVP'),
        actions: [
          IconButton(
            onPressed: _openAdminPage,
            tooltip: 'Admin',
            icon: const Icon(Icons.admin_panel_settings_outlined),
          ),
        ],
      ),
      body: SelectionArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: _questionController,
                decoration: const InputDecoration(
                  labelText: 'Question',
                  border: OutlineInputBorder(),
                ),
                minLines: 2,
                maxLines: 4,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _selectedDomain,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'Domain',
                  border: OutlineInputBorder(),
                ),
                items: [
                  const DropdownMenuItem<String>(
                    value: null,
                    child: Text('Select a domain'),
                  ),
                  ..._domains.map(
                    (domain) => DropdownMenuItem<String>(
                      value: domain,
                      child: Text(domain),
                    ),
                  ),
                ],
                onChanged: _loadingDomains
                    ? null
                    : (value) {
                        setState(() {
                          _selectedDomain = value;
                        });
                      },
              ),
              if (_domainLoadError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_domainLoadError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              if (_selectedDomain == null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Select a domain before asking.',
                    style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
                  ),
                ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: (_loading || _loadingDomains || _selectedDomain == null) ? null : _submit,
                child: Text(_loading ? 'Streaming...' : 'Ask'),
              ),
              const SizedBox(height: 16),
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('1) Upgraded Query (Pre-Retrieval)', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _upgradedQuery.isEmpty
                              ? (_loading ? 'Upgrading query for retrieval...' : 'No upgraded query yet.')
                              : 'Original: ${_originalQuestion.isEmpty ? _questionController.text.trim() : _originalQuestion}\n\nUpgraded: $_upgradedQuery',
                        ),
                      ),
                      if (_queryUpgradePrompt.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Text(
                          'Prompt: $_queryUpgradePrompt',
                          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
                        ),
                      ],
                      const SizedBox(height: 16),
                      const Text('2) Retrieved Documents', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      if (_retrievedDocuments.isEmpty)
                        Text(
                          _loading ? 'Waiting for retrieval results...' : 'No retrieval results yet.',
                          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
                        ),
                      for (final doc in _retrievedDocuments)
                        Card(
                          margin: const EdgeInsets.only(bottom: 10),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '[${doc['rank'] ?? '?'}] ${doc['heading'] ?? 'Untitled'}',
                                  style: const TextStyle(fontWeight: FontWeight.w600),
                                ),
                                const SizedBox(height: 4),
                                Text('${doc['domain'] ?? ''} | score: ${doc['score'] ?? ''}'),
                                const SizedBox(height: 8),
                                const Text(
                                  'Text',
                                  style: TextStyle(fontWeight: FontWeight.w600),
                                ),
                                const SizedBox(height: 4),
                                Text((doc['text'] ?? '').toString()),
                                const SizedBox(height: 8),
                                TextButton(
                                  onPressed: () => _openUrl((doc['url'] ?? '').toString()),
                                  child: Text((doc['url'] ?? '').toString()),
                                ),
                              ],
                            ),
                          ),
                        ),
                      const SizedBox(height: 16),
                      const Text('3) System Prompt (Pre-Generation)', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _systemPrompt.isEmpty ? (_loading ? 'Waiting for system prompt...' : 'No system prompt yet.') : _systemPrompt,
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text('4) Response', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      _buildAnswerWithLinks(context),
                      const SizedBox(height: 16),
                      const Text('Citations', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      for (final citation in _citations)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('[${citation['source']}] ${citation['domain']} - ${citation['heading']}'),
                              TextButton(
                                onPressed: () => _openUrl((citation['url'] ?? '').toString()),
                                child: Text((citation['url'] ?? '').toString()),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class AdminPage extends StatefulWidget {
  const AdminPage({required this.onIngested, super.key});

  final Future<void> Function() onIngested;

  @override
  State<AdminPage> createState() => _AdminPageState();
}

class _AdminPageState extends State<AdminPage> {
  bool _ingesting = false;
  String? _status;

  Future<void> _reingest() async {
    setState(() {
      _ingesting = true;
      _status = null;
    });

    try {
      final response = await http.post(
        Uri.parse('$_apiBase/ingest'),
        headers: const {'content-type': 'application/json'},
        body: jsonEncode(<String, dynamic>{}),
      );

      if (!mounted) return;

      if (response.statusCode < 200 || response.statusCode >= 300) {
        setState(() {
          _status = 'Re-ingest failed (${response.statusCode}): ${response.body}';
        });
        return;
      }

      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      final documents = payload['documents'];
      final chunks = payload['chunks'];
      await widget.onIngested();
      if (!mounted) return;
      setState(() {
        _status = 'Re-ingested $documents documents and $chunks chunks.';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _status = 'Re-ingest failed: $error';
      });
    } finally {
      if (mounted) {
        setState(() {
          _ingesting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Admin')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Data maintenance', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text(
                      'Run a full re-ingest from the configured curated corpus. Existing chunks for documents in that corpus are cleared before new chunks are written.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      onPressed: _ingesting ? null : _reingest,
                      icon: _ingesting
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.sync),
                      label: Text(_ingesting ? 'Re-ingesting...' : 'Re-ingest data'),
                    ),
                  ],
                ),
              ),
            ),
            if (_status != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(_status!),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
