#! /usr/bin/env python
"""Blug is a static blog generator for Markdown based blogs"""

import jinja2
import sys
import markdown
import os
import datetime
import shutil
import argparse
import collections
import blug_server
from copy import copy
try:
    import config_local as config
except ImportError:
    import config

POST_SKELETON = """title: {title}
date: {date}
categories:
"""


def generate_post_file_name(title):
    """Return the file name a post should use based on its title and date"""
    return ''.join(char for char in title.lower() if (
        char.isalnum() or char == ' ')
        ).replace(' ', '-')


def generate_post_file_path(title, date):
    """Return the relative path to a post based on its title and date"""
    return os.path.join(
        datetime.datetime.strftime(date, '%Y/%m/%d/'),
        generate_post_file_name(title))


def get_all_posts(content_dir, blog_prefix, canonical_url, blog_root=None):
    """Return a list of dictionaries representing converted posts"""
    input_files = os.listdir(content_dir)
    all_posts = list()

    for post_file_name in input_files:
        if os.path.splitext(post_file_name)[1] != ".md":
            continue

        post = dict()
        post_output_path = os.path.join(content_dir, post_file_name)
        with open(post_output_path, encoding='ascii') as post_file:
            post_file_buffer = post_file.read()

        # Generate HTML from Markdown, splitting between the teaser (the
        # content to display on the front page until <!--more--> is reached)
        # and the post proper
        mardown_generator = markdown.Markdown(extensions=[
            'fenced_code',
            'codehilite',
            'tables',
            'footnotes',
            'meta',
        ])
        generated_html = mardown_generator.convert(post_file_buffer)
        post['body'] = generated_html
        post['title'] = mardown_generator.Meta['title'][0]
        (post['teaser'], _, _) = generated_html.partition('<!--more-->')
        post['categories'] = mardown_generator.Meta['categories'][0].split()

        # Construct datetime from the *incredibly useful* string YAML
        # provides
        post['date'] = datetime.datetime.strptime(
            (mardown_generator.Meta['date'][0].strip()), '%Y-%m-%d %H:%M')

        # In general we know the layout on disk must match the generated urls
        # This doesn't hold in the case that there is an appendix to the
        # domain that the site resides on. For example, if my WidgetFactory
        # marketing department blog lived at
        # www.widgetfactory.com/marketing/blog/, we would generate the
        # files in the /blog sub-directory but the links would need to
        # include /marketing/blog
        post['relative_path'] = generate_post_file_path(post['title'],
                                                        post['date'])

        if blog_prefix:
            post['relative_path'] = os.path.join(
                blog_prefix, post['relative_path'])

        if blog_root:
            post['relative_url'] = os.path.join('/', blog_root,
                                                post['relative_path'])
        else:
            post['relative_url'] = os.path.join('/', post['relative_path'])

        post['canonical_url'] = canonical_url + post['relative_url']

        all_posts.append(post)
    return all_posts


def create_path_to_file(path):
    """Given a path, make sure all intermediate directories exist; create
    them if they don't"""
    if not os.path.splitext(path)[1]:
        path += '/'
    else:
        path = os.path.dirname(path)
    if not os.path.exists(path):
        os.makedirs(path)


def generate_post(post, template_variables, template_environment):
    """Generate a single post's HTML file"""
    output_path = os.path.join(template_variables['output_dir'],
                               post['relative_path'], 'index.html')

    if not post['body']:
        raise EnvironmentError('No content for post [{post}] found.'.format(
            post=post['relative_path']))

    # Need to keep 'post' and 'site' variables separate
    post_vars = {'post': post}

    template_variables.update(post_vars)
    template = template_environment.get_template('post_index.html')
    create_path_to_file(output_path)
    with open(output_path, 'w') as output:
        output.write(template.render(template_variables))


def generate_static_page(template_variables, output_dir, template,
                         filename='index.html'):
    """Generate a static page"""
    create_path_to_file(output_dir)
    with open(
        os.path.join(
            output_dir, filename), 'w', encoding='ascii') as output_file:
        output_file.write(template.render(template_variables))


def generate_static_files(site_config, posts, categories, template_environment):
    """Generate all 'static' files, files not based on markdown conversion"""
    # Generate an index.html at both the root level and 
    # the 'blog' level, so both www.foo.com and
    # www.foo.com/blog can serve the blog
    list_template = template_environment.get_template('list.html')
    archives_template = template_environment.get_template('archives.html')
    atom_template = template_environment.get_template('atom.xml')
    about_template = template_environment.get_template('about.html')

    if 'additional_pages' in site_config:
        for entry_name in site_config['additional_pages']:
            entry = site_config['additional_pages'][entry_name]
            template_path = entry['template']
            try:
                path = os.path.join(site_config['output_dir'], entry['path'])
            except KeyError:
                path = os.path.join(site_config['output_dir'], entry_name)
            template = template_environment.get_template(template_path)
            generate_static_page(site_config, path, template)

    canonical_url_base = site_config['url']
    canonical_blog_base = '{url}/{blog_prefix}/'.format(
            url=canonical_url_base, 
            blog_prefix=site_config['blog_prefix'])

    # Generate main 'index.html' and '/blog/index.html' pages,
    # showing the five most recent posts
    template_variables = copy(site_config)
    template_variables['next_page'] = 1
    template_variables['canonical_url'] = template_variables['url']
    template_variables['current_posts'] = posts[:5]
    generate_static_page(template_variables,
                         site_config['output_dir'], list_template)

    template_variables['canonical_url'] = canonical_blog_base
    generate_static_page(template_variables,
                         site_config['blog_dir'], list_template)

    # Generate 'about-me' page
    template_variables['canonical_url'] = canonical_url_base + '/about-me/'
    generate_static_page(template_variables,
                         os.path.join(site_config['output_dir'], 'about-me'),
                         about_template)

    # Generate blog archives page
    template_variables['all_posts'] = posts
    template_variables['canonical_url'] = canonical_blog_base + 'archives/'
    generate_static_page(template_variables,
                         os.path.join(site_config['blog_dir'],
                         'archives'), archives_template)

    # Generate atom.xml feed
    template_variables['now'] = datetime.datetime.now().isoformat()
    generate_static_page(template_variables, site_config['output_dir'],
                         atom_template, 'atom.xml')

    # Generate a category "archive" page listing the posts in each category
    for category, posts in categories.items():
        template_variables['all_posts'] = posts
        generate_static_page(template_variables, os.path.join(
            site_config['blog_dir'],
           'categories', category), archives_template)
        generate_static_page(template_variables, os.path.join(
            site_config['blog_dir'],
            'categories', category), atom_template, 'atom.xml')


def generate_pagination_pages(site_config, all_posts, template):
    """Generate the additional index.html files required for pagination"""
    template_variables = copy(site_config)
    num_posts = len(all_posts)
    for index, page in enumerate(
            [all_posts[index:index + 5] for index in range(5, num_posts, 5)]):
        # Overcome the fact that enumerate is 0-indexed
        current_page = index + 1
        # Since we're reusing the index.html template, make it think
        # these posts are the only ones
        template_variables['current_posts'] = page
        template_variables['next_page'] = current_page + 1

        # if we've reached the "last" page, don't present a link to older
        # content
        if (current_page * 5) >= num_posts - 5:
            template_variables['next_page'] = None

        output_dir = os.path.join(site_config['blog_dir'],
                                  'page', str(current_page))
        generate_static_page(template_variables, output_dir, template)


def generate_all_files(site_config):
    """Generate all HTML files from the content directory using the site-wide
    configuration"""
    all_posts = get_all_posts(site_config['content_dir'],
                              site_config['blog_prefix'],
                              site_config['url'],
                              site_config['blog_root'])
    all_posts.sort(key=lambda i: i['date'], reverse=True)
    categories = collections.defaultdict(list)
    for post in all_posts:
        for category in post['categories']:
            categories[category].append(post)

    template_environment = jinja2.Environment(loader=jinja2.FileSystemLoader(
                                              site_config['template_dir']))

    generate_static_files(
            site_config, 
            all_posts, 
            categories, 
            template_environment)

    generate_pagination_pages(
            site_config, 
            all_posts, 
            template_environment.get_template('list.html'))

    for index, post in enumerate(all_posts):
        try:
            post['post_previous'] = all_posts[index + 1]
        except IndexError:
            post['post_previous'] = all_posts[0]
        generate_post(post, site_config, template_environment)


def copy_static_content(output_dir, root_dir):
    """Copy (if necessary) the static content to the appropriate directory"""
    if os.path.exists(output_dir):
        print ('Removing old content...')
        shutil.rmtree(output_dir)
    shutil.copytree(os.path.join(root_dir, 'static'), output_dir)


def create_post(title, content_dir):
    """Create an empty post with the appropriate Markdown metadata format"""
    post_date_time = datetime.datetime.strftime(
        datetime.datetime.now(), '%Y-%m-%d %H:%M')
    post_date = datetime.datetime.strftime(
        datetime.datetime.now(), '%Y-%m-%d')
    post_file_name = '{}-{}.md'.format(
            post_date, 
            generate_post_file_name(title))
    post_file_path = os.path.join(content_dir, post_file_name)

    if os.path.exists(post_file_path):
        raise EnvironmentError('[{post}] already exists.'.format(
            post=post_file_path))

    with open(post_file_path, 'w') as post_file:
        post_file.write(POST_SKELETON.format(date=post_date_time, title=title))


def serve(**kwargs):
    """Serve static HTML pages indefinitely"""
    root = kwargs['root']
    os.chdir(root)


    if kwargs['simple']:
        import http.server
        handler = http.server.SimpleHTTPRequestHandler
        handler.protocol_version = "HTTP/1.0"
        httpd = http.server.HTTPServer((kwargs['host'],
                                        int(kwargs['port'])), handler)

    else:
        handler = blug_server.FileCacheRequestHandler
        httpd = blug_server.BlugHttpServer(root, (kwargs['host'],
                                           int(kwargs['port'])), handler)

    print("serving from {path} on port {port}".format(path=root,
                                                      port=kwargs['port']))
    httpd.serve_forever()


def create_new_post(**kwargs):
    """Reads the appropriate configuration file and generates a new, 
    empty post with the correct file name"""
    site_config = config.CONFIG
    create_post(kwargs['title'], site_config['content_dir'])


def generate_site():
    """Generate the static HTML pages based on the configuration 
    file and content directory"""
    site_config = config.CONFIG

    site_config['blog_dir'] = os.path.join(
        site_config['output_dir'], 
        site_config['blog_prefix'])
    print ('Generating...')

    copy_static_content(site_config['output_dir'], os.getcwd())
    generate_all_files(site_config)

    return True

def main():
    """Main execution of blug"""
    argument_parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='Generate a static HTML blog from  Markdown blog entries')
    subparser = argument_parser.add_subparsers(help='help for sub-commands')

    post_parser = subparser.add_parser(
        'post', help='Create a blank blog post',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    post_parser.add_argument(
        'title', help='Title for the blog post to be generated')
    post_parser.set_defaults(func=create_new_post)

    generate_parser = subparser.add_parser(
        'generate',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help='Generate the complete static site using the posts\
                in the \'content\' directory')
    generate_parser.set_defaults(func=generate_site)

    serve_parser = subparser.add_parser(
        'serve',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help='Start an HTTP server that serves the files under the \
                <content-dir> directory')
    serve_parser.add_argument('-p', '--port', default=8080,
                              help='Port for HTTP server to listen to')
    serve_parser.add_argument('-s', '--host', 
            action='store', 
            default='localhost',
            help='Hostname for HTTP server to serve on')
    serve_parser.add_argument('-r', '--root', 
            action='store', 
            default=os.path.join(os.getcwd(), 'generated'),
            help='Root path to serve files from')
    serve_parser.add_argument('--simple', action='store_true',
            help='Use SimpleHTTPServer instead of Blug\'s web server')
    serve_parser.set_defaults(func=serve)

    parsed_arguments = argument_parser.parse_args()
    arguments = vars(parsed_arguments)
    function = arguments.pop('func')
    if function == generate_site:
        function()
    else:
        function(**arguments)
    print ('Complete')


if __name__ == '__main__':
    sys.exit(main())
